from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Max
from base.forms import InventoryForm
from base.tasks import atualizar_precos_steam_task
from .models import Inventory, InventoryItem, Item, Price, Site
import requests
from django.contrib import messages
from celery import shared_task
from .utils import get_steam_price
from django.utils import timezone   


from .utils import atualizar_precos_steam, importar_inventario

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
    conta_selecionada = None
    itens_com_precos = []
    last_updates = {}

    if conta_id:
        conta_selecionada = get_object_or_404(Inventory, id=conta_id)
        inventory_items = InventoryItem.objects.filter(inventory=conta_selecionada)

        # Pegar último timestamp de cada item
        for inv_item in inventory_items:
            ultimo_preco = (
                Price.objects.filter(item=inv_item.item)
                .order_by("-timestamp")
                .first()
            )
            itens_com_precos.append({
                "nome": inv_item.item.market_hash_name,
                "imagem": inv_item.item.icon_url,
                "preco": ultimo_preco.price if ultimo_preco else inv_item.price_usd,
                "timestamp": ultimo_preco.timestamp if ultimo_preco else None,
                "tradable": inv_item.tradable,
                "float": inv_item.float_value,
                "wear": inv_item.wear_name,
            })

        # Último timestamp geral (mais recente do inventário)
        last_updates = (
            Price.objects.filter(item__inventoryitem__inventory=conta_selecionada)
            .aggregate(last_update=Max("timestamp"))
        )

    return render(request, "dashboard.html", {
        "contas": contas,
        "conta_selecionada": conta_selecionada,
        "itens": itens_com_precos,
        "last_updates": last_updates
    })


def atualizar_precos_view(request, conta_id):
    conta = get_object_or_404(Inventory, id=conta_id)
    atualizar_precos_steam_task.delay(conta.id)  # async
    messages.success(request, "Atualização de preços iniciada! Confira o dashboard em alguns minutos.")
    return redirect("dashboard")
