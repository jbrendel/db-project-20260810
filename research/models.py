"""Run / Category / ContentItem (see plans/INITIAL.md Section 10)."""
from django.db import models

RUN_STATUS = [(s, s) for s in ("blue", "green", "yellow", "red")]
CAT_STATUS = [(s, s) for s in
              ("pending", "running", "green", "yellow", "red")]


class Run(models.Model):
    input_text = models.TextField()
    input_kind = models.CharField(max_length=8)
    resolved_domain = models.CharField(max_length=255, null=True, blank=True)
    owned_profile_urls = models.JSONField(default=list)
    owned_social_handles = models.JSONField(default=list)
    selected_categories = models.JSONField(default=list)
    borderline_options = models.JSONField(default=dict)
    lookback_months = models.IntegerField(default=36)
    status = models.CharField(max_length=8, choices=RUN_STATUS,
                              default="blue")
    generation = models.IntegerField(default=1)
    celery_task_ids = models.JSONField(default=list)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    executive_overview = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    warnings = models.JSONField(default=list)

    class Meta:
        ordering = ["-id"]


class Category(models.Model):
    run = models.ForeignKey(Run, related_name="categories",
                            on_delete=models.CASCADE)
    key = models.CharField(max_length=64)
    is_borderline = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    status = models.CharField(max_length=8, choices=CAT_STATUS,
                              default="pending")
    error = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["display_order"]


class ContentItem(models.Model):
    category = models.ForeignKey(Category, related_name="items",
                                 on_delete=models.CASCADE)
    title = models.TextField()
    url = models.TextField()
    canonical_url = models.TextField()
    source = models.CharField(max_length=255)
    published_at = models.DateTimeField(null=True, blank=True)
    snippet = models.TextField(default="")
    display_order = models.IntegerField(default=0)
    sentiment_score = models.FloatField(null=True, blank=True)
    sentiment_label = models.CharField(max_length=8, null=True, blank=True)

    class Meta:
        ordering = ["display_order"]

    @property
    def is_undated(self):
        return self.published_at is None
