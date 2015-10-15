import re
import urlparse

from operator import attrgetter, itemgetter

from account.models import EmailAddress
from account.views import (LoginView as AccountLoginView,
                           SettingsView as AccountSettingsView,
                           SignupView as AccountSignupView)

from django.apps import apps
from django.contrib import messages as django_messages
from django.contrib.auth import logout
from django.core.urlresolvers import reverse, reverse_lazy
from django.db.models import Count
from django.http import Http404, HttpResponseRedirect
from django.views.generic.base import RedirectView, TemplateView, View
from django.views.generic.detail import DetailView
from django.views.generic.edit import DeleteView, UpdateView
from django.views.generic.list import ListView

from oauth2_provider.models import (
    get_application_model as get_oauth2_application_model,
    AccessToken)
from oauth2_provider.views.base import (
    AuthorizationView as OriginalAuthorizationView)
from oauth2_provider.exceptions import OAuthToolkitError

from common.mixins import NeverCacheMixin, PrivateMixin
from common.utils import querydict_from_dict

from activities.runkeeper.models import UserData as UserDataRunKeeper
from data_import.models import DataRetrievalTask
from public_data.models import PublicDataAccess
from studies.american_gut.models import UserData as UserDataAmericanGut
from studies.go_viral.models import UserData as UserDataGoViral
from studies.pgp.models import UserData as UserDataPgp

from .forms import (MemberLoginForm,
                    MemberSignupForm,
                    MyMemberChangeEmailForm,
                    MyMemberChangeNameForm,
                    MyMemberContactSettingsEditForm,
                    MyMemberProfileEditForm)
from .models import Member


class MemberDetailView(DetailView):
    """
    Creates a view of a member's public profile.
    """
    queryset = Member.enriched.all()
    template_name = 'member/member-detail.html'
    slug_field = 'user__username'

    def get_context_data(self, **kwargs):
        """
        Add context so login and signup return to this page.

        TODO: Document why returning to the page is desired (I think because
        you need to be signed in to contact a member?)
        """
        context = super(MemberDetailView, self).get_context_data(**kwargs)

        context.update({
            'next': reverse_lazy('member-detail',
                                 kwargs={'slug': self.object.user.username}),
            'public_data': self.object.public_data_participant.public_files,
        })

        return context


class MemberListView(ListView):
    """
    Creates a view listing members.
    """
    context_object_name = 'members'
    paginate_by = 100
    template_name = 'member/member-list.html'

    def get_queryset(self):
        if self.request.GET.get('sort') == 'username':
            return (Member.enriched
                    .exclude(user__username='api-administrator')
                    .order_by('user__username'))

        # First sort by name and username
        sorted_members = sorted(Member.enriched
                                .exclude(user__username='api-administrator'),
                                key=attrgetter('user.username'))

        # Then sort by number of badges
        sorted_members = sorted(sorted_members,
                                key=lambda m: len(m.badges),
                                reverse=True)

        return sorted_members

    def get_context_data(self, **kwargs):
        """
        Add context for sorting button.
        """
        context = super(MemberListView, self).get_context_data(**kwargs)

        if self.request.GET.get('sort') == 'username':
            sort_direction = 'connections'
            sort_description = 'by number of connections'
        else:
            sort_direction = 'username'
            sort_description = 'by username'

        context.update({
            'sort_direction': sort_direction,
            'sort_description': sort_description,
        })

        return context


class MyMemberDashboardView(PrivateMixin, DetailView):
    """
    Creates a dashboard for the current user/member.

    The dashboard also displays their public member profile.
    """
    context_object_name = 'member'
    queryset = Member.enriched.all()
    template_name = 'member/my-member-dashboard.html'

    def get_object(self, queryset=None):
        return Member.enriched.get(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super(MyMemberDashboardView, self).get_context_data(**kwargs)

        context.update({
            'public_data':
                self.object.user.member.public_data_participant.public_files,
        })

        return context


class MyMemberProfileEditView(PrivateMixin, UpdateView):
    """
    Creates an edit view of the current user's public member profile.
    """
    form_class = MyMemberProfileEditForm
    model = Member
    template_name = 'member/my-member-profile-edit.html'
    success_url = reverse_lazy('my-member-dashboard')

    def get_object(self, queryset=None):
        return self.request.user.member


class MyMemberSettingsEditView(PrivateMixin, UpdateView):
    """
    Creates an edit view of the current user's member account settings.
    """
    form_class = MyMemberContactSettingsEditForm
    model = Member
    template_name = 'member/my-member-settings.html'
    success_url = reverse_lazy('my-member-settings')

    def get_object(self, queryset=None):
        return self.request.user.member

    def get_context_data(self, **kwargs):
        """
        Add a context variable for whether the email address is verified.
        """
        context = super(MyMemberSettingsEditView,
                        self).get_context_data(**kwargs)

        try:
            email = self.object.user.emailaddress_set.get(primary=True)

            context.update({'email_verified': email.verified is True})
        except EmailAddress.DoesNotExist:
            pass

        return context


class MyMemberChangeEmailView(PrivateMixin, AccountSettingsView):
    """
    Creates a view for the current user to change their email.

    This is an email-only subclass of account's SettingsView.
    """
    form_class = MyMemberChangeEmailForm
    template_name = 'member/my-member-change-email.html'
    success_url = reverse_lazy('my-member-settings')
    messages = {
        'settings_updated': {
            'level': django_messages.SUCCESS,
            'text': 'Email address updated and confirmation email sent.'
        },
    }

    def get_success_url(self, *args, **kwargs):
        kwargs.update(
            {'fallback_url': reverse_lazy('my-member-settings')})
        return super(MyMemberChangeEmailView, self).get_success_url(
            *args, **kwargs)


class MyMemberChangeNameView(PrivateMixin, UpdateView):
    """
    Creates an edit view of the current member's name.
    """
    form_class = MyMemberChangeNameForm
    model = Member
    template_name = 'member/my-member-change-name.html'
    success_url = reverse_lazy('my-member-settings')

    def get_object(self, queryset=None):
        return self.request.user.member


class MyMemberSendConfirmationEmailView(PrivateMixin, RedirectView):
    """
    Send a confirmation email and redirect back to the settings page.
    """
    url = reverse_lazy('my-member-settings')

    def get_redirect_url(self, *args, **kwargs):
        redirect_field_name = self.request.GET.get('redirect_field_name',
                                                   'next')
        next_url = self.request.GET.get(redirect_field_name, self.url)
        return next_url

    def dispatch(self, request, *args, **kwargs):
        email_address = request.user.emailaddress_set.get(primary=True)
        email_address.send_confirmation()
        django_messages.success(request,
                                ('A confirmation email was sent to "{}".'
                                 .format(email_address.email)))
        return super(MyMemberSendConfirmationEmailView, self).dispatch(
            request, *args, **kwargs)


class MyMemberDatasetsView(PrivateMixin, ListView):
    """
    Creates a view for displaying and importing research/activity datasets.
    """
    template_name = 'member/my-member-research-data.html'
    context_object_name = 'data_retrieval_tasks'

    def get_queryset(self):
        # pylint: disable=attribute-defined-outside-init
        self.datasets = (DataRetrievalTask.objects
                         .for_user(self.request.user))

        return self.datasets.normal()

    def get_context_data(self, **kwargs):
        """
        Add a context variable for whether the email address is verified.
        """
        context = super(MyMemberDatasetsView, self).get_context_data(**kwargs)

        context['failed'] = self.datasets.failed()
        context['postponed'] = self.datasets.postponed()

        return context


class MyMemberConnectionsView(PrivateMixin, TemplateView):
    """
    A view for a member to manage their connections.
    """

    template_name = 'member/my-member-connections.html'

    def get_context_data(self, **kwargs):
        """
        Add a context variable for whether the email address is verified.
        """
        context = super(MyMemberConnectionsView, self).get_context_data(
            **kwargs)

        context.update({
            'connections': self.request.user.member.connections.items(),
        })

        return context


class DataRetrievalTaskDeleteView(PrivateMixin, DeleteView):
    """
    Let the user delete a dataset.
    """
    success_url = reverse_lazy('my-member-research-data')

    def get_queryset(self):
        return DataRetrievalTask.objects.filter(user=self.request.user)


class UserDeleteView(PrivateMixin, DeleteView):
    """
    Let the user delete their account.
    """
    context_object_name = 'user'
    template_name = 'account/delete.html'
    success_url = reverse_lazy('home')

    def delete(self, request, *args, **kwargs):
        response = super(UserDeleteView, self).delete(request, *args, **kwargs)

        # Log the user out prior to deleting them so that they don't appear
        # logged in when they're redirected to the homepage.
        logout(request)

        return response

    def get_object(self, queryset=None):
        return self.request.user


class MyMemberConnectionDeleteView(PrivateMixin, TemplateView):
    """
    Let the user delete a connection.
    """

    template_name = 'member/my-member-connections-delete.html'

    def get_access_tokens(self, connection):
        connections = self.request.user.member.connections

        if connection not in connections:
            raise Http404()

        access_tokens = AccessToken.objects.filter(
            user=self.request.user,
            application__name=connections[connection]['verbose_name'],
            application__user__username='api-administrator')

        return access_tokens

    def get_context_data(self, **kwargs):
        context = super(MyMemberConnectionDeleteView, self).get_context_data(
            **kwargs)

        connection = kwargs.get('connection', None)
        connections = self.request.user.member.connections

        context.update({
            'connection_name': connections[connection]['verbose_name'],
        })

        return context

    def post(self, request, **kwargs):
        connection = kwargs.get('connection', None)

        if not connection:
            return

        if connection in ('american_gut', 'go_viral', 'pgp'):
            access_tokens = self.get_access_tokens(connection)
            access_tokens.delete()

            return HttpResponseRedirect(reverse('my-member-connections'))

        if connection == 'runkeeper':
            django_messages.error(
                request,
                ('Sorry, RunKeeper connections must currently be removed by '
                 'visiting http://runkeeper.com/settings/apps'))

            return HttpResponseRedirect(reverse('my-member-connections'))


class ExceptionView(View):
    """
    Raises an exception for testing purposes.
    """
    @staticmethod
    def get(request):  # pylint: disable=unused-argument
        raise Exception('A test exception.')


class MemberSignupView(AccountSignupView):
    """
    Creates a view for signing up for a Member account.

    This is a subclass of accounts' SignupView using our form customizations,
    including addition of a name field and a TOU confirmation checkbox.
    """
    form_class = MemberSignupForm

    def create_account(self, form):
        account = super(MemberSignupView, self).create_account(form)

        # We only create Members from this view, which means that if a User has
        # a Member then they've signed up to Open Humans and are a participant.
        member = Member(user=account.user)
        member.save()

        account.user.member.name = form.cleaned_data['name']
        account.user.member.save()

        return account

    def generate_username(self, form):
        """Override as StandardError instead of NotImplementedError."""
        raise StandardError(
            'Username must be supplied by form data.'
        )


class MemberLoginView(AccountLoginView):
    """
    A version of account's LoginView that requires the User to be a Researcher.
    """
    form_class = MemberLoginForm


class OAuth2LoginView(TemplateView):
    """
    Give people authorizing with us the ability to easily sign up or log in.
    """
    template_name = 'account/login-oauth2.html'

    def get_context_data(self, **kwargs):
        ctx = kwargs

        next_querystring = querydict_from_dict({
            'next': self.request.GET.get('next')
        }).urlencode()

        ctx.update({
            'next_querystring': next_querystring,
            'connection': self.request.GET.get('connection'),
            'panel_width': 8,
            'panel_offset': 2,
        })

        return super(OAuth2LoginView, self).get_context_data(**ctx)


def app_from_label(app_label):
    """
    Return an app given an app_label or None if the app is not found.
    """
    app_configs = apps.get_app_configs()
    matched_apps = [a for a in app_configs if a.label == app_label]

    if matched_apps and len(matched_apps) == 1:
        return matched_apps[0]

    return None


def origin(string):
    """
    Coerce an origin to 'open-humans' or 'external', defaulting to 'external'
    """
    return 'open-humans' if string == 'open-humans' else 'external'


class AuthorizationView(OriginalAuthorizationView):
    """
    Override oauth2_provider view to add origin, context, and customize login
    prompt.
    """

    is_study_app = False

    def create_authorization_response(self, request, scopes, credentials,
                                      allow):
        """
        Add the origin to the callback URL.
        """
        uri, headers, body, status = (
            super(AuthorizationView, self).create_authorization_response(
                request, scopes, credentials, allow))

        uri += '&origin={}'.format(origin(request.GET.get('origin')))

        return (uri, headers, body, status)

    def dispatch(self, request, *args, **kwargs):
        """
        Override dispatch, if unauthorized use a custom login-or-signup view.

        This renders redundant the LoginRequiredMixin used by the parent class
        (oauth_provider.views.base's AuthorizationView).
        """
        if request.user.is_authenticated():
            return (super(AuthorizationView, self)
                    .dispatch(request, *args, **kwargs))

        try:
            # Get requesting application for custom login-or-signup
            _, credentials = self.validate_authorization_request(request)

            application_model = get_oauth2_application_model()

            application = application_model.objects.get(
                client_id=credentials['client_id'])
        except OAuthToolkitError as error:
            return self.error_response(error)

        querydict = querydict_from_dict({
            'next': request.get_full_path(),
            'connection': str(application.name)
        })

        url = reverse('account_login_oauth2')

        url_parts = list(urlparse.urlparse(url))
        url_parts[4] = querydict.urlencode()

        return HttpResponseRedirect(urlparse.urlunparse(url_parts))

    @staticmethod
    def _check_study_app_request(context):
        """
        Return true if this OAuth2 request matches a study app
        """
        # NOTE: This assumes 'scopes' was overwritten by get_context_data.
        scopes = [x[0] for x in context['scopes']]

        try:
            scopes.remove('read')
            scopes.remove('write')
        except ValueError:
            return False

        if not len(scopes) == 1:
            return False

        app_label = re.sub('-', '_', scopes[0])
        app = app_from_label(app_label)

        if app and app.verbose_name == context['application'].name:
            return app_label

        return False

    def get_context_data(self, **kwargs):
        context = super(AuthorizationView, self).get_context_data(**kwargs)

        context.update({
            'panel_width': 8,
            'panel_offset': 2
        })

        def scope_key(zipped_scope):
            scope, _ = zipped_scope

            # Sort 'write' second to last
            if scope == 'write':
                return 'zzy'

            # Sort 'read' last
            if scope == 'read':
                return 'zzz'

            # Sort all other scopes alphabetically
            return scope

        def scope_class(scope):
            if scope in ['read', 'write']:
                return 'info'

            return 'primary'

        zipped_scopes = zip(context['scopes'], context['scopes_descriptions'])
        zipped_scopes.sort(key=scope_key)

        context['scopes'] = [(scope, description, scope_class(scope))
                             for scope, description in zipped_scopes]

        # For custom display when it's for a study app connection.
        app_label = self._check_study_app_request(context)

        if app_label:
            self.is_study_app = True

            context['app_label'] = app_label
            context['is_study_app'] = True
            context['scopes'] = [x for x in context['scopes']
                                 if x[0] != 'read' and x[0] != 'write']

        return context

    def get_template_names(self):
        if self.is_study_app:
            return ['oauth2_provider/finalize.html']

        return [self.template_name]


class SourcesContextMixin(object):
    """
    A mixin for adding context for connection sources to a template.
    """

    def get_context_data(self, **kwargs):
        context = super(SourcesContextMixin, self).get_context_data(**kwargs)

        context.update({
            'sources': {
                'american_gut': UserDataAmericanGut,
                'go_viral': UserDataGoViral,
                'pgp': UserDataPgp,
                'runkeeper': UserDataRunKeeper,
            }
        })

        return context


class ActivitiesView(NeverCacheMixin, SourcesContextMixin, TemplateView):
    """
    A simple TemplateView for the activities page that doesn't cache.
    """

    template_name = 'pages/activities.html'


class StatisticsView(TemplateView):
    """
    A simple TemplateView for Open Humans statistics.
    """
    template_name = 'pages/statistics.html'

    @staticmethod
    def get_connections():
        application_model = get_oauth2_application_model()

        return (application_model.objects
                .order_by('name')
                .annotate(count=Count('user')))

    @staticmethod
    def get_files(is_public):
        files = (PublicDataAccess.objects
                 .filter(is_public=is_public)
                 .values('data_file_model__app_label')
                 .annotate(count=Count('data_file_model__app_label')))

        for f in files:
            app_label = f.pop('data_file_model__app_label')
            app = app_from_label(app_label)

            f['app'] = app.verbose_name

        # sort here instead of in the database since we need to look up the
        # Django app name
        return sorted(files, key=itemgetter('app'))

    def get_context_data(self, **kwargs):
        context = super(StatisticsView, self).get_context_data(**kwargs)

        context.update({
            'members': Member.objects.count(),
            'connections': self.get_connections(),
            'private_files': self.get_files(is_public=False),
            'public_files': self.get_files(is_public=True),
        })

        return context


class WelcomeView(PrivateMixin, SourcesContextMixin, TemplateView):
    """
    A template view that doesn't cache, and is private.
    """
    template_name = 'member/welcome.html'
