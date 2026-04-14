from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Q
from django.contrib import messages
from django.db.models.functions import TruncMonth
from .models import Transaction, Contact, Product, Quotation
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
    search_query = request.GET.get('search_query', '').strip()
    
    transactions = Transaction.objects.all()
    
    if search_query:
        transactions = transactions.filter(Q(title__icontains=search_query) | Q(tag__icontains=search_query))
        
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

    # Chart data (chronological order)
    chart_data = list(reversed(summary_list))
    chart_labels = json.dumps([s['period'].strftime('%Y-%m') for s in chart_data])
    chart_income = json.dumps([float(s['INCOME'] + s['SELL']) for s in chart_data])
    chart_expense = json.dumps([float(s['EXPENSE'] + s['BUY']) for s in chart_data])

    context = {
        'transactions': transactions[:100],  # show latest 100
        'summary_list': summary_list,
        'available_months': available_months_qs,
        'filter_month': filter_month,
        'category': category,
        'search_query': search_query,
        'chart_labels': chart_labels,
        'chart_income': chart_income,
        'chart_expense': chart_expense,
    }
    return render(request, 'finance/dashboard.html', context)

@login_required
def add_transaction(request):
    if request.method == 'POST':
        # Get data
        t_type = request.POST.get('transaction_type')
        title = request.POST.get('title')
        tag = request.POST.get('tag', '')
        price = request.POST.get('price')
        has_vat = request.POST.get('has_vat') == 'on'
        date_str = request.POST.get('date')
        receipt_file = request.FILES.get('receipt_file')
        
        contact_id = request.POST.get('contact')
        product_id = request.POST.get('product')
        quantity = int(request.POST.get('quantity') or 1)
        payment_status = request.POST.get('payment_status', 'PAID')
        
        currency = request.POST.get('currency', 'THB')
        exchange_rate = Decimal(request.POST.get('exchange_rate', '1.0'))
        raw_price = request.POST.get('price')
        expense_category = request.POST.get('expense_category', 'N/A')
        
        contact = get_object_or_404(Contact, id=contact_id) if contact_id else None
        product = get_object_or_404(Product, id=product_id) if product_id else None
        
        # Execute create
        if t_type and title and raw_price and date_str:
            t = Transaction(
                transaction_type=t_type,
                title=title,
                tag=tag,
                has_vat=has_vat,
                date=datetime.datetime.strptime(date_str, '%Y-%m-%d').date(),
                receipt_file=receipt_file,
                contact=contact,
                product=product,
                quantity=quantity,
                payment_status=payment_status,
                currency=currency,
                exchange_rate=exchange_rate,
                expense_category=expense_category,
                created_by=request.user
            )
            p_val = Decimal(raw_price)
            if currency == 'THB':
                t.price = p_val
            else:
                t.foreign_price = p_val
                t.price = p_val * exchange_rate
            t.save()
            
            # Stock logic
            if product:
                if t_type == 'BUY': product.stock_quantity += quantity
                elif t_type == 'SELL': product.stock_quantity -= quantity
                product.save()
                
            return redirect('dashboard')
            
    default_date = request.GET.get('default_date', '')
    context = {
        'default_date': default_date,
        'contacts': Contact.objects.all(),
        'products': Product.objects.all(),
    }
    return render(request, 'finance/transaction_form.html', context)

@login_required
def edit_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id)
    
    if request.method == 'POST':
        t_type = request.POST.get('transaction_type')
        title = request.POST.get('title')
        tag = request.POST.get('tag', '')
        price = request.POST.get('price')
        has_vat = request.POST.get('has_vat') == 'on'
        date_str = request.POST.get('date')
        receipt_file = request.FILES.get('receipt_file')
        
        # ERP logic: refund old stock before applying the new
        old_product = transaction.product
        old_qty = transaction.quantity
        old_type = transaction.transaction_type
        
        if old_product:
            if old_type == 'BUY': old_product.stock_quantity -= old_qty
            elif old_type == 'SELL': old_product.stock_quantity += old_qty
            old_product.save()

        contact_id = request.POST.get('contact')
        product_id = request.POST.get('product')
        quantity = int(request.POST.get('quantity') or 1)
        payment_status = request.POST.get('payment_status', 'PAID')
        
        currency = request.POST.get('currency', 'THB')
        exchange_rate = Decimal(request.POST.get('exchange_rate', '1.0'))
        raw_price = request.POST.get('price')
        expense_category = request.POST.get('expense_category', 'N/A')
        
        contact = get_object_or_404(Contact, id=contact_id) if contact_id else None
        product = get_object_or_404(Product, id=product_id) if product_id else None
        
        if t_type and title and raw_price and date_str:
            transaction.transaction_type = t_type
            transaction.title = title
            transaction.tag = tag
            transaction.has_vat = has_vat
            transaction.date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            transaction.contact = contact
            transaction.product = product
            transaction.quantity = quantity
            transaction.payment_status = payment_status
            transaction.currency = currency
            transaction.exchange_rate = exchange_rate
            transaction.expense_category = expense_category
            
            p_val = Decimal(raw_price)
            if currency == 'THB':
                transaction.price = p_val
            else:
                transaction.foreign_price = p_val
                
            if receipt_file:
                transaction.receipt_file = receipt_file
            transaction.save()
            
            # Apply new stock
            if product:
                if t_type == 'BUY': product.stock_quantity += quantity
                elif t_type == 'SELL': product.stock_quantity -= quantity
                product.save()
                
            return redirect('dashboard')
            
    context = {
        'transaction': transaction,
        'contacts': Contact.objects.all(),
        'products': Product.objects.all(),
    }
    return render(request, 'finance/transaction_form.html', context)

@login_required
def delete_transaction(request, transaction_id):
    if not request.user.is_superuser:
        messages.error(request, 'ไม่มีสิทธิ์ลบรายการ')
        return redirect('dashboard')
        
    transaction = get_object_or_404(Transaction, id=transaction_id)
    if request.method == 'POST':
        # Refund stock
        if transaction.product:
            if transaction.transaction_type == 'BUY': transaction.product.stock_quantity -= transaction.quantity
            elif transaction.transaction_type == 'SELL': transaction.product.stock_quantity += transaction.quantity
            transaction.product.save()
        transaction.delete()
        messages.success(request, 'ลบรายการและคืนสต๊อกแล้ว')
    return redirect('dashboard')

@login_required
def print_invoice(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id)
    return render(request, 'finance/invoice_pdf.html', {'transaction': transaction})

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

@login_required
def product_list(request):
    products = Product.objects.all().order_by('-created_at')
    return render(request, 'finance/product_list.html', {'products': products})

@login_required
def add_product(request):
    if request.method == 'POST':
        code = request.POST.get('code')
        name = request.POST.get('name')
        price = request.POST.get('price', 0)
        stock_quantity = request.POST.get('stock_quantity', 0)
        
        if code and name:
            Product.objects.create(
                code=code, name=name,
                price=Decimal(price) if price else 0,
                stock_quantity=int(stock_quantity) if stock_quantity else 0
            )
            return redirect('product_list')
    return render(request, 'finance/product_form.html')

@login_required
def edit_product(request, product_id):
    p = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        p.code = request.POST.get('code')
        p.name = request.POST.get('name')
        price = request.POST.get('price')
        p.price = Decimal(price) if price else 0
        stock = request.POST.get('stock_quantity')
        p.stock_quantity = int(stock) if stock else 0
        p.save()
        return redirect('product_list')
    return render(request, 'finance/product_form.html', {'product': p})

@login_required
def contact_list(request):
    contacts = Contact.objects.all().order_by('-created_at')
    return render(request, 'finance/contact_list.html', {'contacts': contacts})

@login_required
def add_contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        tax_id = request.POST.get('tax_id', '')
        address = request.POST.get('address', '')
        c_type = request.POST.get('contact_type', 'CUSTOMER')
        
        if name:
            Contact.objects.create(name=name, tax_id=tax_id, address=address, contact_type=c_type)
            return redirect('contact_list')
    return render(request, 'finance/contact_form.html')

@login_required
def edit_contact(request, contact_id):
    c = get_object_or_404(Contact, id=contact_id)
    if request.method == 'POST':
        c.name = request.POST.get('name')
        c.tax_id = request.POST.get('tax_id', '')
        c.address = request.POST.get('address', '')
        c.contact_type = request.POST.get('contact_type', 'CUSTOMER')
        c.save()
        return redirect('contact_list')
@login_required
def import_csv(request):
    if request.method == 'POST':
        if 'csv_file' not in request.FILES:
            return redirect('import_csv')
            
        csv_file = request.FILES['csv_file']
        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'กรุณาอัปโหลดไฟล์ .csv เท่านั้น')
            return redirect('import_csv')
            
        decoded_file = csv_file.read().decode('utf-8-sig').splitlines()
        reader = csv.reader(decoded_file)
        
        first_row = True
        count = 0
        for row in reader:
            if first_row:
                first_row = False
                continue
            
            if len(row) >= 4:
                try:
                    date_val = datetime.datetime.strptime(row[0].strip(), '%Y-%m-%d').date()
                    t_type = row[1].strip().upper()
                    if t_type not in ['BUY', 'SELL', 'INCOME', 'EXPENSE']:
                        t_type = 'INCOME'
                    title = row[2].strip()
                    price = Decimal(row[3].strip())
                    
                    has_vat = False
                    if len(row) > 4:
                        has_vat = str(row[4]).strip() == '1'
                        
                    qty = 1
                    if len(row) > 5 and row[5].strip():
                        qty = int(row[5].strip())
                        
                    status = 'PAID'
                    if len(row) > 6 and row[6].strip():
                        status = row[6].strip().upper()
                        
                    tag = ''
                    if len(row) > 7:
                        tag = row[7].strip()
                        
                    Transaction.objects.create(
                        date=date_val, transaction_type=t_type, title=title, price=price,
                        has_vat=has_vat, quantity=qty, payment_status=status, tag=tag,
                        created_by=request.user
                    )
                    count += 1
                except Exception as e:
                    pass
        messages.success(request, f'นำเข้าสำเร็จ {count} รายการ')
        return redirect('dashboard')
        
    return render(request, 'finance/csv_import.html')

@login_required
def quotation_list(request):
    quotations = Quotation.objects.all().order_by('-created_at')
    return render(request, 'finance/quotation_list.html', {'quotations': quotations})

@login_required
def add_quotation(request):
    if request.method == 'POST':
        t_type = request.POST.get('transaction_type')
        title = request.POST.get('title')
        tag = request.POST.get('tag', '')
        has_vat = request.POST.get('has_vat') == 'on'
        date_str = request.POST.get('date')
        receipt_file = request.FILES.get('receipt_file')
        
        contact_id = request.POST.get('contact')
        product_id = request.POST.get('product')
        quantity = int(request.POST.get('quantity') or 1)
        
        currency = request.POST.get('currency', 'THB')
        exchange_rate = Decimal(request.POST.get('exchange_rate', '1.0'))
        raw_price = request.POST.get('price')
        
        contact = get_object_or_404(Contact, id=contact_id) if contact_id else None
        product = get_object_or_404(Product, id=product_id) if product_id else None
        
        if t_type and title and raw_price and date_str:
            q = Quotation(
                transaction_type=t_type,
                title=title,
                tag=tag,
                has_vat=has_vat,
                date=datetime.datetime.strptime(date_str, '%Y-%m-%d').date(),
                receipt_file=receipt_file,
                contact=contact,
                product=product,
                quantity=quantity,
                currency=currency,
                exchange_rate=exchange_rate,
                expense_category=request.POST.get('expense_category', 'N/A'),
                status='DRAFT',
                created_by=request.user
            )
            # Route price correctly based on currency
            p_val = Decimal(raw_price)
            if currency == 'THB':
                q.price = p_val
            else:
                q.foreign_price = p_val
                q.price = p_val * exchange_rate # Temporary to pass validation, save will recalculate
            q.save()
            return redirect('quotation_list')
            
    context = {
        'contacts': Contact.objects.all(),
        'products': Product.objects.all(),
    }
    return render(request, 'finance/quotation_form.html', context)

@login_required
def edit_quotation(request, quotation_id):
    q = get_object_or_404(Quotation, id=quotation_id)
    if q.is_converted:
        messages.error(request, 'ใบเสนอราคาถูกอ้างอิงเป็นบิลจริงแล้ว ไม่สามารถแก้ไขได้')
        return redirect('quotation_list')

    if request.method == 'POST':
        t_type = request.POST.get('transaction_type')
        title = request.POST.get('title')
        tag = request.POST.get('tag', '')
        has_vat = request.POST.get('has_vat') == 'on'
        date_str = request.POST.get('date')
        receipt_file = request.FILES.get('receipt_file')
        
        contact_id = request.POST.get('contact')
        product_id = request.POST.get('product')
        quantity = int(request.POST.get('quantity') or 1)
        
        currency = request.POST.get('currency', 'THB')
        exchange_rate = Decimal(request.POST.get('exchange_rate', '1.0'))
        raw_price = request.POST.get('price')
        
        status = request.POST.get('status', 'DRAFT')
        
        if t_type and title and raw_price and date_str:
            q.transaction_type = t_type
            q.title = title
            q.tag = tag
            q.has_vat = has_vat
            q.date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            if receipt_file:
                q.receipt_file = receipt_file
                
            q.contact = get_object_or_404(Contact, id=contact_id) if contact_id else None
            q.product = get_object_or_404(Product, id=product_id) if product_id else None
            q.quantity = quantity
            q.currency = currency
            q.exchange_rate = exchange_rate
            q.expense_category = request.POST.get('expense_category', 'N/A')
            q.status = status
            
            p_val = Decimal(raw_price)
            if currency == 'THB':
                q.price = p_val
            else:
                q.foreign_price = p_val
            q.save()
            return redirect('quotation_list')
            
    context = {
        'quotation': q,
        'contacts': Contact.objects.all(),
        'products': Product.objects.all(),
    }
    return render(request, 'finance/quotation_form.html', context)

@login_required
def delete_quotation(request, quotation_id):
    if not request.user.is_superuser:
        messages.error(request, 'ไม่มีสิทธิ์ลบ')
        return redirect('quotation_list')
    q = get_object_or_404(Quotation, id=quotation_id)
    if request.method == 'POST':
        q.delete()
        messages.success(request, 'ลบเอกสารใบเสนอราคาแล้ว')
    return redirect('quotation_list')

@login_required
def convert_quotation(request, quotation_id):
    q = get_object_or_404(Quotation, id=quotation_id)
    
    if q.is_converted:
        messages.warning(request, 'เอกสารนี้ได้ถูกแปลงไปแล้ว!')
        return redirect('quotation_list')
        
    if q.status != 'APPROVED':
        messages.error(request, 'ต้องอนุมัติ (APPROVED) เอกสารก่อนจึงจะแปลงเป็นบิลจริงได้')
        return redirect('quotation_list')
        
    # Create the mirror Transaction
    t = Transaction.objects.create(
        transaction_type=q.transaction_type,
        title=q.title,
        price=q.price,
        foreign_price=q.foreign_price,
        currency=q.currency,
        exchange_rate=q.exchange_rate,
        has_vat=q.has_vat,
        tag=q.tag,
        date=timezone.now().date(),
        contact=q.contact,
        product=q.product,
        quantity=q.quantity,
        expense_category=q.expense_category,
        payment_status='PENDING', # Needs payment obviously
        created_by=request.user,
        receipt_file=q.receipt_file
    )
    
    # Inventory Math
    if t.product:
        if t.transaction_type == 'BUY': t.product.stock_quantity += t.quantity
        elif t.transaction_type == 'SELL': t.product.stock_quantity -= t.quantity
        t.product.save()
        
    q.is_converted = True
    q.save()
    messages.success(request, '🎉 แปลงเป็นบิลจริงและปรับสต๊อกเรียบร้อยแล้ว!')
    return redirect('dashboard')

@login_required
def executive_analytics(request):
    transactions = Transaction.objects.filter(payment_status='PAID') # Only calculate actual settled money for P&L

    total_sales = transactions.filter(transaction_type__in=['INCOME', 'SELL']).aggregate(Sum('total_price'))['total_price__sum'] or 0
    cogs = transactions.filter(expense_category='COGS').aggregate(Sum('total_price'))['total_price__sum'] or 0
    opex = transactions.filter(expense_category='OPEX').aggregate(Sum('total_price'))['total_price__sum'] or 0
    capex = transactions.filter(expense_category='CAPEX').aggregate(Sum('total_price'))['total_price__sum'] or 0
    
    gross_profit = total_sales - cogs
    net_profit = gross_profit - opex

    top_customers = transactions.filter(transaction_type__in=['INCOME', 'SELL'], contact__isnull=False)\
        .values('contact__name')\
        .annotate(total=Sum('total_price'))\
        .order_by('-total')[:5]

    top_products = transactions.filter(transaction_type='SELL', product__isnull=False)\
        .values('product__name')\
        .annotate(qty=Sum('quantity'))\
        .order_by('-qty')[:5]

    import json
    context = {
        'total_sales': total_sales,
        'cogs': cogs,
        'opex': opex,
        'capex': capex,
        'gross_profit': gross_profit,
        'net_profit': net_profit,
        'top_customers_json': json.dumps(list(top_customers), default=str),
        'top_products_json': json.dumps(list(top_products), default=str),
    }

    return render(request, 'finance/analytics.html', context)
