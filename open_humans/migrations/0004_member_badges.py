# -*- coding: utf-8 -*-
# Generated by Django 1.9.2 on 2016-02-25 05:22
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('open_humans', '0003_auto_20151223_1827'),
    ]

    operations = [
        migrations.AddField(
            model_name='member',
            name='badges',
            field=django.contrib.postgres.fields.jsonb.JSONField(default=dict),
        ),
    ]
