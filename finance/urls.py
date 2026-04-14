from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('add/', views.add_transaction, name='add_transaction'),
    path('edit/<int:transaction_id>/', views.edit_transaction, name='edit_transaction'),
    path('delete/<int:transaction_id>/', views.delete_transaction, name='delete_transaction'),
    path('export/csv/', views.export_csv, name='export_csv'),
    path('export/json/', views.export_json, name='export_json'),
    path('invoice/<int:transaction_id>/', views.print_invoice, name='print_invoice'),
    
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/edit/<int:product_id>/', views.edit_product, name='edit_product'),
    
    path('contacts/', views.contact_list, name='contact_list'),
    path('contacts/add/', views.add_contact, name='add_contact'),
    path('contacts/edit/<int:contact_id>/', views.edit_contact, name='edit_contact'),
    
    path('import_csv/', views.import_csv, name='import_csv'),
    
    path('quotations/', views.quotation_list, name='quotation_list'),
    path('quotations/add/', views.add_quotation, name='add_quotation'),
    path('quotations/edit/<int:quotation_id>/', views.edit_quotation, name='edit_quotation'),
    path('quotations/delete/<int:quotation_id>/', views.delete_quotation, name='delete_quotation'),
    path('quotations/convert/<int:quotation_id>/', views.convert_quotation, name='convert_quotation'),
    
    path('analytics/', views.executive_analytics, name='executive_analytics'),
]
