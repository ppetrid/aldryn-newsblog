# -*- coding: utf-8 -*-

from django.contrib.sites.models import Site
from django.contrib.syndication.views import Feed
from easy_thumbnails.files import get_thumbnailer

try:
    from django.contrib.sites.shortcuts import get_current_site
except ImportError:
    # Django 1.6
    from django.contrib.sites.models import get_current_site
from django.core.urlresolvers import reverse
from django.utils.translation import get_language_from_request, ugettext as _

from aldryn_apphooks_config.utils import get_app_instance
from aldryn_categories.models import Category
from aldryn_newsblog.models import Article
from aldryn_newsblog.utils.utilities import get_valid_languages


class LatestArticlesFeed(Feed):
    def __call__(self, request, *args, **kwargs):
        self.namespace, self.config = get_app_instance(request)
        self.scheme = request.scheme
        self.language = get_language_from_request(request, check_path=True)
        site_id = getattr(get_current_site(request), 'id', None)
        self.valid_languages = get_valid_languages(
            self.namespace,
            language_code=self.language,
            site_id=site_id)
        return super(LatestArticlesFeed, self).__call__(
            request, *args, **kwargs)

    def link(self):
        return reverse('{0}:article-list-feed'.format(self.namespace))

    def title(self):
        return _('Articles on {0}').format(Site.objects.get_current().name)

    def get_queryset(self):
        qs = Article.objects.published() \
            .translated(*self.valid_languages) \
            .active_translations(self.language) \
            .namespace(self.namespace)

        return qs

    def items(self, obj):
        qs = self.get_queryset()
        return qs.order_by('-publishing_date')[:10]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return '%s%s%s' % (self.item_image(item),
                         item.lead_in,
                         self.item_original(item))

    def item_pubdate(self, item):
        return item.publishing_date

    def item_image(self, item):
        if not item.featured_image:
            return ''

        thumbnailer = get_thumbnailer(item.featured_image)
        try:
            thumb = thumbnailer.get_thumbnail({
                    'crop': True,
                    'size': (767, 337),
                    'subject_location': item.featured_image.subject_location
            })
        except:
            return ''

        return '<img width="747" height="345" ' \
                'src="%s://%s%s" alt="%s" style="display: block; ' \
                'margin-bottom: 10px;" />' % (
                    self.scheme,
                    Site.objects.get_current().domain, 
                    thumb.url,
                    item.title
                )

    def item_original(self, item):
        return '<p>%s</p>' % \
            _('The post <a href="%(scheme)s://' \
              '%(domain)s%(post_url)s" title="%(post_title)s">' \
              '%(post_title)s</a> appeared first on ' \
              '<a href="%(scheme)s://%(domain)s%(blog_url)s '\
              'title="%(site_title)s blog">%(site_title)s blog</a>') % {
                    'scheme': self.scheme,
                    'domain': Site.objects.get_current().domain,
                    'post_url': item.get_absolute_url(),
                    'post_title': item.title,
                    'blog_url': reverse('%s:article-list' % self.namespace),
                    'site_title': Site.objects.get_current().name
            }


class TagFeed(LatestArticlesFeed):

    def get_object(self, request, tag):
        return tag

    def items(self, obj):
        return self.get_queryset().filter(tags__slug=obj)[:10]


class CategoryFeed(LatestArticlesFeed):

    def get_object(self, request, category):
        language = get_language_from_request(request, check_path=True)
        return Category.objects.language(language).translated(
            *self.valid_languages, slug=category).get()

    def items(self, obj):
        return self.get_queryset().filter(categories=obj)[:10]
