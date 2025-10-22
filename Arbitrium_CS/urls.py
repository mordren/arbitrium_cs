from django.contrib import admin
from django.urls import path
from base.views import (
    atualizar_inventario,    
    atualizar_precos_view,
    dashboard,
    cadastrar_inventory,
    preco_alvo_view,
    definir_preco_alvo_view,
    
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("cadastrar/", cadastrar_inventory, name="cadastrar_inventory"),
    path("atualizar/<int:conta_id>/", atualizar_inventario, name="atualizar_inventario"),
    path("atualizar-precos/<int:conta_id>/", atualizar_precos_view, name="atualizar_precos"),

    # >>> Novas rotas:
    path("precos/", preco_alvo_view, name="preco_alvo"),
    path("precos/definir/", definir_preco_alvo_view, name="definir_preco_alvo"),        
    

]