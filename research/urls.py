"""research app URLconf (mounted under /api/ by drumbeat/urls.py)."""
from django.urls import path
from research import views

urlpatterns = [
    path("runs/", views.RunListCreateView.as_view()),
    path("runs/<int:pk>/", views.RunDetailView.as_view()),
    path("runs/<int:pk>/refresh/", views.RunRefreshView.as_view()),
]
