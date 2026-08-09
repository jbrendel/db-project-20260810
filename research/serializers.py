"""DRF serializers and the run-create validator (§11 contract)."""
import os
from django.utils import timezone
from rest_framework import serializers
from research.models import Run, Category, ContentItem
from research.categories import (selected_category_keys, DISPLAY_ORDER,
                                 BORDERLINE_CATEGORIES)
from research import urls_util


class ContentItemSerializer(serializers.ModelSerializer):
    is_undated = serializers.BooleanField(read_only=True)

    class Meta:
        model = ContentItem
        fields = ["title", "url", "source", "published_at", "is_undated",
                  "snippet", "display_order", "sentiment_score",
                  "sentiment_label", "sentiment_summary"]


class CategorySerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()
    items = ContentItemSerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ["key", "is_borderline", "display_order", "status", "error",
                  "summary", "item_count", "items"]

    def get_item_count(self, obj):
        # len(all()) uses the prefetch cache on the polled detail path (one
        # query for all items), falling back to a single query otherwise.
        return len(obj.items.all())  # server-computed; frontend never counts


def _iter_months(start_ym, end_ym):
    """Yield (year, month) inclusive from start_ym to end_ym (both (y, m))."""
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y


def _window_start(ref, lookback_months):
    """First (year, month) of a lookback_months window ending in ref's month."""
    index = ref.year * 12 + (ref.month - 1) - (lookback_months - 1)
    return index // 12, index % 12 + 1


class RunDetailSerializer(serializers.ModelSerializer):
    total_item_count = serializers.SerializerMethodField()
    sentiment_timeline = serializers.SerializerMethodField()
    sentiment_summary = serializers.SerializerMethodField()
    categories = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = Run
        fields = ["id", "input_text", "input_kind", "status", "started_at",
                  "ended_at", "executive_overview", "error", "warnings",
                  "total_item_count", "sentiment_timeline",
                  "sentiment_summary", "categories"]

    def get_total_item_count(self, obj):
        # Sum over the prefetched categories/items so the polled detail path
        # adds no extra queries (§10: counts are server-computed).
        return sum(len(c.items.all()) for c in obj.categories.all())

    def _all_items(self, obj):
        for cat in obj.categories.all():          # prefetched -> no N+1
            for item in cat.items.all():
                yield item

    def get_sentiment_timeline(self, obj):
        ref = obj.started_at or timezone.now()
        start_ym = _window_start(ref, obj.lookback_months)
        buckets = {}
        for item in self._all_items(obj):
            if item.published_at is not None and \
                    item.sentiment_score is not None:
                key = (item.published_at.year, item.published_at.month)
                buckets.setdefault(key, []).append(item.sentiment_score)
        out = []
        for (y, m) in _iter_months(start_ym, (ref.year, ref.month)):
            scores = buckets.get((y, m), [])
            avg = round(sum(scores) / len(scores), 3) if scores else None
            out.append({"month": f"{y:04d}-{m:02d}", "avg_score": avg,
                        "item_count": len(scores)})
        return out

    def get_sentiment_summary(self, obj):
        scored, undated_scored, unknown = [], 0, 0
        for item in self._all_items(obj):
            if item.sentiment_score is None:
                unknown += 1
            else:
                scored.append(item.sentiment_score)
                if item.published_at is None:
                    undated_scored += 1
        overall = round(sum(scored) / len(scored), 3) if scored else None
        return {"overall_avg": overall, "scored_count": len(scored),
                "undated_scored_count": undated_scored,
                "unknown_count": unknown}


class RunListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Run
        fields = ["id", "input_text", "status", "started_at"]


class RunCreateSerializer(serializers.Serializer):
    """Validate a run-create request; every failure maps to a 400 (§11)."""
    input_text = serializers.CharField(required=False, allow_blank=True,
                                       trim_whitespace=False)
    lookback_months = serializers.IntegerField(required=False)
    borderline_options = serializers.DictField(required=False)

    def validate(self, attrs):
        text = (attrs.get("input_text") or "").strip()
        if not text:
            raise serializers.ValidationError(
                {"input_text": "Input (company name or URL) must not be empty."})
        max_len = int(os.environ.get("MAX_INPUT_LENGTH", "2000"))
        if len(text) > max_len:
            raise serializers.ValidationError(
                {"input_text": f"Input must be at most {max_len} characters."})

        kind = urls_util.detect_input_kind(text)
        resolved_domain = None
        if kind == "url":
            if urls_util.parse_homepage_input(text) is None:
                raise serializers.ValidationError(
                    {"input_text": "That looks like a URL but is not a valid "
                                   "web address."})
            resolved_domain = urls_util.registrable_domain(text)

        months = attrs.get("lookback_months", 36)
        if months is None:
            months = 36
        if not (1 <= months <= 600):
            raise serializers.ValidationError(
                {"lookback_months": "look-back must be between 1 and 600 "
                                    "months."})

        borderline = attrs.get("borderline_options") or {}
        # Checkbox semantics: values must be real booleans. A string like
        # "false" is truthy, so silently coercing it would wrongly enable a
        # category — reject it (fail loud, §16).
        for key, value in borderline.items():
            if not isinstance(value, bool):
                raise serializers.ValidationError(
                    {"borderline_options":
                     f"value for '{key}' must be true or false."})
        try:
            selected = selected_category_keys(borderline)
        except KeyError as exc:
            # str(KeyError(msg)) wraps msg in single quotes; strip those.
            raise serializers.ValidationError(
                {"borderline_options": str(exc).strip("'")})
        if not selected:  # defensive: a no-op run is invalid (§11)
            raise serializers.ValidationError(
                {"borderline_options": "No categories selected."})

        attrs.update(input_text=text, input_kind=kind,
                     resolved_domain=resolved_domain, lookback_months=months,
                     borderline_options=borderline, selected_categories=selected)
        return attrs

    def create(self, validated):
        selected = validated["selected_categories"]
        run = Run.objects.create(
            input_text=validated["input_text"],
            input_kind=validated["input_kind"],
            resolved_domain=validated["resolved_domain"],
            selected_categories=selected,
            borderline_options=validated["borderline_options"],
            lookback_months=validated["lookback_months"],
        )
        _create_categories(run, selected)
        return run


def _create_categories(run, selected):
    """Create the pending Category rows for a run, in display order."""
    Category.objects.bulk_create([
        Category(run=run, key=key,
                 is_borderline=key in BORDERLINE_CATEGORIES,
                 display_order=DISPLAY_ORDER[key], status="pending")
        for key in selected])
