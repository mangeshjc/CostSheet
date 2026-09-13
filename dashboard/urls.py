from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("analytics/", views.analytics, name="analytics"),
    path("orders/", views.orders, name="orders"),
    path("customers/", views.customers, name="customers"),
    path("settings/", views.settings_view, name="settings"),
    path("upload-erp/", views.upload_erp, name="upload_erp"),
    path("erp-files/", views.erp_files, name="erp_files"),
    path("scp/artr-data/", views.artr_data, name="artr_data"),
    path("scp/artr-data/build/", views.artr_build, name="artr_build"),
    path("scp/sales-stage/", views.sales_stage, name="sales_stage"),
    path("scp/sales-reconciliation/", views.sales_recon, name="sales_recon"),
    path("output/horizontal-cs/", views.horizontal_cs, name="horizontal_cs"),
]
