# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aldryn_newsblog', '0011_auto_20160412_1622'),
    ]

    operations = [
        migrations.AddField(
            model_name='newsblogconfig',
            name='pagination_link_type',
            field=models.CharField(default='param', help_text='Choose the style of urls to use for the pagination.', max_length=5, verbose_name='pagination permalink type', choices=[('param', 'URL parameter (e.g. "my-slug/?page=2")'), ('url', 'Permalink (e.g. "my-slug/page/2/")')]),
        ),
    ]
