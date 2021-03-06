# -*- coding: utf-8 -*-
# Generated by Django 1.9.9 on 2016-09-09 04:27
from __future__ import unicode_literals

from string import digits  # pylint: disable=deprecated-module

from django.db import migrations

from common.utils import generate_id


def migrate_go_viral_files(apps, *args):
    Application = apps.get_model('oauth2_provider', 'Application')
    Member = apps.get_model('open_humans', 'Member')
    DataFile = apps.get_model('data_import', 'DataFile')
    OAuth2DataRequestProject = apps.get_model('private_sharing',
                                              'OAuth2DataRequestProject')
    DataRequestProjectMember = apps.get_model('private_sharing',
                                              'DataRequestProjectMember')
    ProjectDataFile = apps.get_model('private_sharing', 'ProjectDataFile')
    PublicDataAccess = apps.get_model('public_data', 'PublicDataAccess')

    try:
        UserData = apps.get_model('go_viral', 'UserData')
    except LookupError:
        return

    try:
        rumi = Member.objects.get(user__username='rumichunara')
    except Member.DoesNotExist:
        return

    def random_id():
        code = generate_id(size=8, chars=digits)

        while DataRequestProjectMember.objects.filter(
                project_member_id=code).count() > 0:
            code = generate_id(size=8, chars=digits)

        return code

    application = Application()

    application.name = 'GoViral (2014-2016)'
    application.user = rumi.user
    application.client_type = 'confidential'
    application.redirect_uris = 'https://www.openhumans.org/'
    application.authorization_grant_type = 'authorization-code'

    application.save()

    project = OAuth2DataRequestProject(
        application=application,
        is_study=True,
        name='GoViral (2014-2016)',
        leader='Dr. Rumi Chunara',
        organization='NYU Polytechnic School of Engineering',
        is_academic_or_nonprofit=True,
        contact_email='goviralstudy@gmail.com',
        info_url='https://www.goviralstudy.com/',
        short_description="""Participants in this viral surveillance study
        received kits, and sent samples if they got sick.""",
        long_description="""This project represents previous years of the
        GoViral study. Participants in this viral surveillance study received
        kits, and sent samples if they got sick. Data import from this study is
        no longer available, but data remains in member accounts if it was
        previously imported.""",
        returned_data_description="""Sickness reports contain survey data from
        GoViral. Viral profiling data contains raw viral test results.""",
        active=False,
        coordinator=rumi,
        request_message_permission=False,
        request_username_access=False,
        approved=True,
        # these two URLs are never used but need to be valid URLs for
        # validation to succeed in the admin
        enrollment_url='https://www.openhumans.org/',
        redirect_url='https://www.openhumans.org/')

    project.save()

    (PublicDataAccess.objects
     .filter(data_source='go_viral')
     .update(data_source='direct-sharing-{}'.format(project.id)))

    for data_file in DataFile.objects.filter(source='go_viral'):
        project_file = ProjectDataFile(
            direct_sharing_project=project,
            file=data_file.file,
            created=data_file.created,
            metadata=data_file.metadata,
            source='direct-sharing-{}'.format(project.id),
            user=data_file.user,
            archived=data_file.archived)

        project_file.save()

    DataFile.objects.filter(source='go_viral').delete()

    for user_data in UserData.objects.all():
        if not user_data.data.get('goViralId', None):
            continue

        member = DataRequestProjectMember(
            member=user_data.user.member,
            project_member_id=random_id(),
            project=project,
            consent_text='',
            joined=True,
            authorized=True)

        member.save()


class Migration(migrations.Migration):

    dependencies = [
        ('public_data', '0001_squashed_0004_auto_20151230_0050'),
        ('private_sharing', '0002_add_project_data_file'),
    ]

    operations = [
        migrations.RunPython(migrate_go_viral_files),
    ]
