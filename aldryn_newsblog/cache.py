import hashlib
from django.conf import settings
from django.utils.encoding import iri_to_uri, force_text
from django.utils.timezone import get_current_timezone_name
from cms.cache import _get_cache_version, _set_cache_version
from cms.utils import get_cms_setting
from django.utils.cache import add_never_cache_headers


def _blog_page_cache_key(request):
    """ The blog page cache key will take the cookie language into account """
    #md5 key of current path
    cache_key = "%s:%d:%s:%s" % (
        get_cms_setting("CACHE_PREFIX"),
        settings.SITE_ID,
        request.COOKIES.get('sitelpref', 'na'),
        hashlib.md5(iri_to_uri(request.get_full_path()).encode('utf-8')).hexdigest()
    )
    if settings.USE_TZ:
        # The datetime module doesn't restrict the output of tzname().
        # Windows is known to use non-standard, locale-dependant names.
        # User-defined tzinfo classes may return absolutely anything.
        # Hence this paranoid conversion to create a valid cache key.
        tz_name = force_text(get_current_timezone_name(), errors='ignore')
        cache_key += '.%s' % tz_name.encode('ascii', 'ignore').decode('ascii').replace(' ', '_')
    return cache_key


def set_blog_page_cache(response):
    from django.core.cache import cache

    if not get_cms_setting('PAGE_CACHE'):
        return response
    request = response._request
    save_cache = True
    for placeholder in getattr(request, 'placeholders', []):
        if not placeholder.cache_placeholder:
            save_cache = False
            break
    if hasattr(request, 'toolbar'):
        if request.toolbar.edit_mode or request.toolbar.show_toolbar:
            save_cache = False
    if request.user.is_authenticated():
        save_cache = False
    if not save_cache:
        add_never_cache_headers(response)
        return response
    else:
        version = _get_cache_version()
        ttl = get_cms_setting('CACHE_DURATIONS')['content']

        cache.set(
            _blog_page_cache_key(request),
            (response.content, response._headers),
            ttl,
            version=version
        )
        # See note in invalidate_cms_page_cache()
        _set_cache_version(version)


def get_blog_page_cache(request):
    from django.core.cache import cache

    return cache.get(_blog_page_cache_key(request),
                     version=_get_cache_version())
