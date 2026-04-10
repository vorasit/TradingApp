from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from .models import Transaction
from decimal import Decimal
from django.utils import timezone
import datetime
import csv
import json
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required

@login_required
def dashboard(request):
    filter_month = request.GET.get('filter_month', 'all')
    category = request.GET.get('category', 'all')
    
    transactions = Transaction.objects.all()
    
    # Filter by category if requested
    valid_categories = dict(Transaction.TRANSACTION_TYPES).keys()
    if category != 'all' and category in valid_categories:
        transactions = transactions.filter(transaction_type=category)
        
    # Filter by specific month
    if filter_month != 'all':
        try:
            y, m = filter_month.split('-')
            transactions = transactions.filter(date__year=int(y), date__month=int(m))
        except:
            pass
        
    # Order transactions for the table below
    transactions = transactions.order_by('-date', '-created_at')
    
    # Available months list for dropdown
    available_months_qs = Transaction.objects.dates('date', 'month', order='DESC')
    
    monthly_data = (
        transactions
        .annotate(period=TruncMonth('date'))
        .values('period', 'transaction_type')
        .annotate(total=Sum('total_price'), vat=Sum('vat_amount'), base=Sum('price'))
        .order_by('-period')
    )
    
    # Restructure data for easier template rendering
    summary_by_period = {}
    for item in monthly_data:
        if not item['period']:
            continue
            
        period_label = item['period'].strftime('%Y-%m-%d')
        if period_label not in summary_by_period:
            summary_by_period[period_label] = {
                'period': item['period'],
                'BUY': Decimal('0'), 'SELL': Decimal('0'), 
                'INCOME': Decimal('0'), 'EXPENSE': Decimal('0'),
                'VAT_PAID': Decimal('0'), 'VAT_RECEIVED': Decimal('0'),
                'NET_PROFIT': Decimal('0')
            }
            
        t_type = item['transaction_type']
        summary_by_period[period_label][t_type] += item['total']
        
        # Track VAT separately for Buy vs Sell
        if t_type == 'BUY':
            summary_by_period[period_label]['VAT_PAID'] += item['vat']
        elif t_type == 'SELL':
            summary_by_period[period_label]['VAT_RECEIVED'] += item['vat']

    # Calculate net profit for each period
    for val in summary_by_period.values():
        val['NET_PROFIT'] = (val['SELL'] + val['INCOME']) - (val['BUY'] + val['EXPENSE'])

    # Sort dictionary by period descending
    summary_list = list(summary_by_period.values())
    summary_list.sort(key=lambda x: x['period'], reverse=True)

    context = {
        'transactions': transactions[:100],  # show latest 100
        'summary_list': summary_list,
        'available_months': available_months_qs,
        'filter_month': filter_month,
        'category': category,
    }
    return render(request, 'finance/dashboard.html', context)

@login_required
def add_transaction(request):
    if request.method == 'POST':
        # Get data
        t_type = request.POST.get('transaction_type')
        title = request.POST.get('title')
        price = request.POST.get('price')
        has_vat = request.POST.get('has_vat') == 'on'
        date_str = request.POST.get('date')
        
        # Execute create
        if t_type and title and price and date_str:
            Transaction.objects.create(
                transaction_type=t_type,
                title=title,
                price=Decimal(price),
                has_vat=has_vat,
                date=datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            )
            return redirect('dashboard')
            
    default_date = request.GET.get('default_date', '')
    context = {
        'default_date': default_date
    }
    return render(request, 'finance/transaction_form.html', context)

@login_required
def edit_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id)
    
    if request.method == 'POST':
        t_type = request.POST.get('transaction_type')
        title = request.POST.get('title')
        price = request.POST.get('price')
        has_vat = request.POST.get('has_vat') == 'on'
        date_str = request.POST.get('date')
        
        if t_type and title and price and date_str:
            transaction.transaction_type = t_type
            transaction.title = title
            transaction.price = Decimal(price)
            transaction.has_vat = has_vat
            transaction.date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            transaction.save()
            return redirect('dashboard')
            
    context = {
        'transaction': transaction
    }
    return render(request, 'finance/transaction_form.html', context)

@login_required
def delete_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id)
    if request.method == 'POST':
        transaction.delete()
    return redirect('dashboard')

@login_required
def export_csv(request):
    filter_month = request.GET.get('filter_month', 'all')
    category = request.GET.get('category', 'all')
    
    transactions = Transaction.objects.all()
    
    if category != 'all' and category in dict(Transaction.TRANSACTION_TYPES).keys():
        transactions = transactions.filter(transaction_type=category)
        
    if filter_month != 'all':
        try:
            y, m = filter_month.split('-')
            transactions = transactions.filter(date__year=int(y), date__month=int(m))
        except: pass
        
    transactions = transactions.order_by('-date', '-created_at')

    response = HttpResponse(content_type='text/csv')
    response.write('\ufeff'.encode('utf8')) # BOM for Excel
    response['Content-Disposition'] = f'attachment; filename="transactions_export_{filter_month}_{category}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['วันที่ทำรายการ', 'ประเภท', 'รายการ', 'ยอดเงิน(ตั้งต้น)', 'VAT 7%', 'ยอดสุทธิ(รวมVAT)', 'วันที่บันทึกระบบ'])
    
    for t in transactions:
        writer.writerow([
            t.date.strftime('%Y-%m-%d'),
            t.get_transaction_type_display(),
            t.title,
            t.price,
            t.vat_amount if t.has_vat else 0,
            t.total_price,
            t.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return response

@login_required
def export_json(request):
    filter_month = request.GET.get('filter_month', 'all')
    category = request.GET.get('category', 'all')
    
    transactions = Transaction.objects.all()
    
    if category != 'all' and category in dict(Transaction.TRANSACTION_TYPES).keys():
        transactions = transactions.filter(transaction_type=category)
        
    if filter_month != 'all':
        try:
            y, m = filter_month.split('-')
            transactions = transactions.filter(date__year=int(y), date__month=int(m))
        except: pass
        
    transactions = transactions.order_by('-date', '-created_at')

    data = []
    for t in transactions:
        data.append({
            'date': t.date.strftime('%Y-%m-%d'),
            'transaction_type': t.transaction_type,
            'type_display': t.get_transaction_type_display(),
            'title': t.title,
            'price_base': float(t.price),
            'has_vat': t.has_vat,
            'vat_amount': float(t.vat_amount),
            'total_price': float(t.total_price),
            'system_created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
        
    response = JsonResponse({'transactions': data}, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="transactions_export_{filter_month}_{category}.json"'
    return response
