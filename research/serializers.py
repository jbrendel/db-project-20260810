"""DRF serializers and the run-create validator (§11 contract)."""
import os
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
                  "snippet", "display_order"]


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


class RunDetailSerializer(serializers.ModelSerializer):
    total_item_count = serializers.SerializerMethodField()
    categories = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = Run
        fields = ["id", "input_text", "input_kind", "status", "started_at",
                  "ended_at", "executive_overview", "error", "warnings",
                  "total_item_count", "categories"]

    def get_total_item_count(self, obj):
        # Sum over the prefetched categories/items so the polled detail path
        # adds no extra queries (§10: counts are server-computed).
        return sum(len(c.items.all()) for c in obj.categories.all())


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
