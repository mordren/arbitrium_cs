import os
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Max
from base.forms import InventoryForm
from base.tasks import atualizar_precos_steam_task
from .models import Inventory, InventoryItem, Item, Price, PriceAlvo, Site
import requests
from django.contrib import messages
from celery import shared_task
from .utils import calcular_valor_total_bruto, calcular_valor_total_liquido, get_steam_price
from django.utils import timezone   
from django.core.paginator import Paginator
from django.shortcuts import render
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery, F
from django.urls import reverse
from django.views.decorators.http import require_POST
from kombu.exceptions import OperationalError  # para capturar erro de publish
from .utils import importar_inventario



def atualizar_inventario(request, conta_id):
    conta = get_object_or_404(Inventory, id=conta_id)
    try:
        importar_inventario(conta.steam_id, conta)
        messages.success(request, "Inventário atualizado com sucesso!")
    except Exception as e:
        messages.error(request, f"Erro ao atualizar inventário: {e}")
    return redirect("dashboard")

def dashboard(request):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {
        "currency": 1,
        "appid": 730,
        "market_hash_name": "Danger Zone Case"
    }

    resp = requests.get(url, params=params).json()
    data = {}
    if resp.get("success"):
        data = {
            "name": "Danger Zone Case",
            "lowest": resp.get("lowest_price"),
            "median": resp.get("median_price"),
            "volume": resp.get("volume"),
        }

    return render(request, "dashboard.html", {"data": data})


def cadastrar_inventory(request):
    if request.method == "POST":
        form = InventoryForm(request.POST)
        if form.is_valid():
            inventory = Inventory(
                name=form.cleaned_data["name"],
                steam_id=form.cleaned_data["steam_id"]
            )
            inventory.save()
            return redirect("dashboard")
    else:
        form = InventoryForm()
    return render(request, "cadastrar_inventario.html", {"form": form})


def dashboard(request):
    contas = Inventory.objects.all()
    conta_id = request.GET.get("conta")
    conta = contas.filter(id=conta_id).first() if conta_id else None

    itens = None
    valor_total = 0
    item_mais_caro = None
    last_updates = {"last_update": None}

    if conta:
        # anota preço/timestamp atuais para listar os cards
        latest_price_sq = Price.objects.filter(item=OuterRef("item")).order_by("-timestamp").values("price")[:1]
        latest_ts_sq    = Price.objects.filter(item=OuterRef("item")).order_by("-timestamp").values("timestamp")[:1]

        itens = (
            conta.items.select_related("item")
            .annotate(
                nome=F("item__market_hash_name"),
                imagem=F("item__icon_url"),
                preco=Subquery(latest_price_sq),
                timestamp=Subquery(latest_ts_sq),
            )
            .order_by("-preco")
        )

        # total BRUTO (para o card que você mostrou)
        valor_total = calcular_valor_total_bruto(conta)

        # se quiser ter o total líquido também (opcional):
        valor_total_liquido = calcular_valor_total_liquido(conta)

        # item mais caro (pelo preço atual bruto)
        item_mais_caro = itens.first()

        # última atualização (maior timestamp entre itens)
        last_updates["last_update"] = itens.aggregate(mx=Max("timestamp"))["mx"]

    ctx = {
        "contas": contas,
        "conta_selecionada": conta,
        "itens": itens,
        "valor_total": valor_total,                 # usado no template
        "valor_total_liquido": locals().get("valor_total_liquido"),
        "item_mais_caro": item_mais_caro,
        "last_updates": last_updates,
    }
    return render(request, "dashboard.html", ctx)

def atualizar_precos_view(request, conta_id):
    conta = get_object_or_404(Inventory, id=conta_id)
    atualizar_precos_steam_task.delay(conta.id)  # async
    messages.success(request, "Atualização de preços iniciada! Confira o dashboard em alguns minutos.")
    return redirect("dashboard")

def preco_alvo_view(request):
    contas = Inventory.objects.all()
    conta_id = request.GET.get("conta")
    conta = contas.filter(id=conta_id).first() if conta_id else None

    itens_page = None
    if conta:
        # último preço/timestamp do Item
        latest_price_sq = (
            Price.objects
            .filter(item=OuterRef("item"))
            .order_by("-timestamp")
            .values("price")[:1]
        )
        latest_ts_sq = (
            Price.objects
            .filter(item=OuterRef("item"))
            .order_by("-timestamp")
            .values("timestamp")[:1]
        )

        # preço alvo para a conta selecionada
        alvo_sq = (
            PriceAlvo.objects
            .filter(item=OuterRef("item"), inventory=conta)
            .values("preco_alvo")[:1]
        )

        itens_qs = (
            conta.items.select_related("item")
            .annotate(
                # IMPORTANTE: use um nome que NÃO conflita com campos do InventoryItem
                item_pk=F("item__id"),
                nome=F("item__market_hash_name"),
                imagem=F("item__icon_url"),   # <- seu Item tem 'icon_url'
                preco=Subquery(latest_price_sq),
                timestamp=Subquery(latest_ts_sq),
                preco_alvo=Subquery(alvo_sq)
            )
            .order_by("item__market_hash_name")   # evita warning na paginação
            .values("item_pk", "nome", "imagem", "preco", "timestamp", "preco_alvo")
        )

        paginator = Paginator(itens_qs, 24)
        itens_page = paginator.get_page(request.GET.get("page"))

    ctx = {
        "contas": contas,
        "conta_selecionada": conta,
        "itens": itens_page,
    }
    return render(request, "preco_alvo.html", ctx)

@require_POST
def definir_preco_alvo_view(request):
    item_id = request.POST.get("item_id")
    inventory_id = request.POST.get("inventory_id") or request.GET.get("conta")

    if not (item_id and inventory_id):
        messages.error(request, "Requisição inválida: item ou conta ausentes.")
        return redirect("preco_alvo")

    conta = get_object_or_404(Inventory, pk=inventory_id)
    item = get_object_or_404(Item, pk=item_id)

    raw_price = (request.POST.get("target_price") or "").strip()
    try:
        preco_alvo = Decimal(raw_price)
        if preco_alvo < 0:
            raise InvalidOperation
    except Exception:
        messages.error(request, "Preço alvo inválido.")
        return redirect(reverse("preco_alvo") + f"?conta={conta.id}")

    PriceAlvo.objects.update_or_create(
        item=item,
        inventory=conta,
        defaults={"preco_alvo": preco_alvo},
    )
    messages.success(request, "Preço alvo salvo com sucesso.")
    return redirect(reverse("preco_alvo") + f"?conta={conta.id}")
