from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db import models


class BlogPost(models.Model):
    author = models.ForeignKey(User)
    title = models.CharField(max_length=50)
    timestamp = models.DateTimeField()
    body = models.TextField()
    summary = models.CharField(max_length=100)
    slug = models.SlugField()
    url_fields = {
        'slug': 'slug',
    }

    class Meta:
        ordering = ['-timestamp']

    def __unicode__(self):
        return "%s (%s)" % (self.title, self.timestamp.strftime("%B %d, %Y"))

    def get_absolute_url(self):
        return reverse('news_view', args=[self.slug])

    def get_num_comments(self):
        return self.blogcomment_set.count()


class BlogComment(models.Model):
    author = models.ForeignKey(User)
    post = models.ForeignKey(BlogPost)
    body = models.TextField()
