from django.urls import path

from .views import login_view, logout_view, me_view, register_view

urlpatterns = [
    path("register", register_view, name="auth-register"),
    path("login", login_view, name="auth-login"),
    path("logout", logout_view, name="auth-logout"),
    path("me", me_view, name="auth-me"),
]
