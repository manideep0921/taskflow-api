from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    # API routes
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/projects/', include('apps.projects.urls')),
    path('api/v1/tasks/', include('apps.tasks.urls')),
    # Frontend catch-all — serves the SPA
    path('', TemplateView.as_view(template_name='index.html'), name='index'),
    path('<path:path>', TemplateView.as_view(template_name='index.html'), name='spa'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
