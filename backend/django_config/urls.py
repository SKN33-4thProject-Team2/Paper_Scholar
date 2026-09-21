"""
URL configuration for django_config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # 1. Django 관리자 콘솔
    path('admin/', admin.site.urls),

    # 2. 사용자용 Scholar API 엔드포인트
    path('api/', include('scholar.urls')),

    # 3. 루트(/) 진입 시 /api/papers/ 로 자동 이동
    path('', RedirectView.as_view(url='/api/papers/', permanent=False)),
]
