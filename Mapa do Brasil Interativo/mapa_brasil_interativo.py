"""
Mapa Interativo do Brasil - 26 estados + Distrito Federal

Recursos:
- Utiliza a malha das 27 Unidades da Federação.
- Ao passar o mouse sobre uma unidade, exibe:
    * nome completo
    * sigla
    * população estimada
- População baseada na estimativa oficial do IBGE com referência em 01/07/2026.
- A malha GeoJSON é baixada automaticamente uma única vez e armazenada
  localmente para permitir novas execuções sem novo download.
- O mapa é aberto no navegador padrão e não usa WebSocket.

Fonte da malha:
IBGE, disponibilizada em GeoJSON pelo projeto br-geojson:
https://github.com/henriquemalvar/br-geojson

Fonte da população:
IBGE - Estimativas da População 2026:
https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/estimativa_dou_2026.pdf
"""

from __future__ import annotations

import json
import html
import os
import sys
import tempfile
import urllib.request
import webbrowser
from pathlib import Path

import folium
from branca.colormap import LinearColormap
from folium.features import GeoJson, GeoJsonTooltip, GeoJsonPopup


GEOJSON_URL = (
    "https://cdn.jsdelivr.net/gh/henriquemalvar/br-geojson@main/dist/estados.geojson"
)

CACHE_FILE = Path(__file__).with_name("brasil_estados.geojson")


# População estimada pelo IBGE, com data de referência em 01/07/2026.
POPULACAO_2026 = {
    "RO": 1_757_338,
    "AC": 887_794,
    "AM": 4_360_926,
    "RR": 761_012,
    "PA": 8_756_324,
    "AP": 809_953,
    "TO": 1_595_994,
    "MA": 7_024_557,
    "PI": 3_392_617,
    "CE": 9_302_211,
    "RN": 3_463_737,
    "PB": 4_182_828,
    "PE": 9_583_176,
    "AL": 3_221_128,
    "SE": 2_307_255,
    "BA": 14_889_472,
    "MG": 21_460_311,
    "ES": 4_150_692,
    "RJ": 17_225_410,
    "SP": 46_179_008,
    "PR": 11_952_456,
    "SC": 8_312_759,
    "RS": 11_233_317,
    "MS": 2_946_317,
    "MT": 3_950_330,
    "GO": 7_495_033,
    "DF": 3_009_996,
}


def formatar_populacao(valor: int) -> str:
    """Formata números no padrão brasileiro."""
    return f"{valor:,}".replace(",", ".")


def baixar_malha() -> dict:
    """
    Baixa a malha GeoJSON na primeira execução e mantém uma cópia local.

    Isso evita depender da internet em todas as execuções posteriores.
    """
    if CACHE_FILE.exists():
        try:
            with CACHE_FILE.open("r", encoding="utf-8") as arquivo:
                return json.load(arquivo)
        except (OSError, json.JSONDecodeError):
            # Se o arquivo local estiver corrompido, será baixado novamente.
            pass

    print("Baixando a malha dos estados brasileiros...")
    try:
        request = urllib.request.Request(
            GEOJSON_URL,
            headers={"User-Agent": "MapaBrasilInterativo/1.0"},
        )

        with urllib.request.urlopen(request, timeout=30) as resposta:
            dados = resposta.read()

        geojson = json.loads(dados.decode("utf-8"))

        with CACHE_FILE.open("w", encoding="utf-8") as arquivo:
            json.dump(geojson, arquivo, ensure_ascii=False)

        return geojson

    except Exception as erro:
        raise RuntimeError(
            "Não foi possível obter a malha dos estados.\n\n"
            "Verifique sua conexão com a internet na primeira execução "
            "e tente novamente.\n\n"
            f"Detalhe técnico: {erro}"
        ) from erro


def obter_sigla(feature: dict) -> str:
    """Obtém a sigla da UF da estrutura do GeoJSON."""
    props = feature.get("properties", {})

    # O projeto br-geojson utiliza 'sigla'.
    sigla = props.get("sigla")

    if sigla:
        return str(sigla).upper()

    # Fallbacks para facilitar compatibilidade com outras malhas.
    for chave in ("SIGLA", "uf", "UF", "abbrev", "id"):
        valor = props.get(chave)
        if valor:
            valor = str(valor).upper()
            if len(valor) == 2:
                return valor

    raise KeyError(f"Não foi possível identificar a sigla: {props}")


def enriquecer_geojson(geojson: dict) -> dict:
    """
    Adiciona os dados populacionais ao GeoJSON.

    Assim o Folium consegue usar os dados diretamente no tooltip.
    """
    features = geojson.get("features", [])

    if len(features) != 27:
        raise RuntimeError(
            f"A malha retornada possui {len(features)} unidades, mas eram "
            "esperadas exatamente 27 (26 estados + DF)."
        )

    siglas_encontradas = set()

    for feature in features:
        props = feature.setdefault("properties", {})

        sigla = obter_sigla(feature)
        nome = props.get("nome") or props.get("NOME")

        if not nome:
            raise RuntimeError(
                f"A unidade {sigla} não possui nome na malha GeoJSON."
            )

        if sigla not in POPULACAO_2026:
            raise RuntimeError(
                f"Não existe população cadastrada para a UF {sigla}."
            )

        populacao = POPULACAO_2026[sigla]

        props["nome"] = nome
        props["sigla"] = sigla
        props["populacao_2026"] = populacao
        props["populacao_formatada"] = formatar_populacao(populacao)

        siglas_encontradas.add(sigla)

    ausentes = set(POPULACAO_2026) - siglas_encontradas
    extras = siglas_encontradas - set(POPULACAO_2026)

    if ausentes or extras:
        raise RuntimeError(
            f"Problema de correspondência das UFs. Ausentes={sorted(ausentes)} "
            f"Extras={sorted(extras)}"
        )

    return geojson


def criar_mapa(geojson: dict) -> folium.Map:
    """Cria e configura o mapa interativo do Brasil."""

    mapa = folium.Map(
        location=[-14.2, -52.8],
        zoom_start=4,
        min_zoom=3,
        max_zoom=8,
        tiles="CartoDB positron",
        control_scale=True,
        prefer_canvas=True,
    )

    # Escala de cores baseada na população das UFs.
    escala = LinearColormap(
        colors=[
            "#E8F5E9",
            "#A5D6A7",
            "#66BB6A",
            "#2E7D32",
        ],
        vmin=min(POPULACAO_2026.values()),
        vmax=max(POPULACAO_2026.values()),
    )

    escala.caption = "População estimada da Unidade da Federação — IBGE 2026"
    escala.add_to(mapa)

    def estilo_padrao(feature: dict) -> dict:
        sigla = obter_sigla(feature)
        populacao = POPULACAO_2026[sigla]

        return {
            "fillColor": escala(populacao),
            "color": "#202020",
            "weight": 1.4,
            "fillOpacity": 0.82,
        }

    def estilo_hover(feature: dict) -> dict:
        sigla = obter_sigla(feature)
        populacao = POPULACAO_2026[sigla]

        return {
            "fillColor": escala(populacao),
            "color": "#111111",
            "weight": 3.0,
            "fillOpacity": 1.0,
        }

    tooltip = GeoJsonTooltip(
        fields=[
            "nome",
            "sigla",
            "populacao_formatada",
        ],
        aliases=[
            "Estado:",
            "Sigla:",
            "População estimada (2026):",
        ],
        labels=True,
        sticky=True,
        localize=True,
        style=(
            "background-color: white; "
            "color: #111; "
            "font-family: Arial, sans-serif; "
            "font-size: 13px; "
            "padding: 10px; "
            "border-radius: 8px; "
            "box-shadow: 0 2px 12px rgba(0,0,0,0.20);"
        ),
        style_hover=(
            "background-color: #F8F9FA; "
            "font-weight: bold;"
        ),
    )

    popup = GeoJsonPopup(
        fields=[
            "nome",
            "sigla",
            "populacao_formatada",
        ],
        aliases=[
            "Estado:",
            "Sigla:",
            "População estimada (2026):",
        ],
        labels=True,
        localize=True,
        style=(
            "background-color: white; "
            "font-family: Arial, sans-serif; "
            "font-size: 14px;"
        ),
    )

    camada = GeoJson(
        data=geojson,
        name="26 estados + Distrito Federal",
        style_function=estilo_padrao,
        highlight_function=estilo_hover,
        tooltip=tooltip,
        popup=popup,
        smooth_factor=0.5,
        zoom_on_click=False,
        show=True,
    )

    camada.add_to(mapa)

    # Painel superior explicativo.
    painel = """
    <div style="
        position: fixed;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 9999;
        background: rgba(255,255,255,0.96);
        padding: 12px 18px;
        border-radius: 12px;
        border: 1px solid #d9d9d9;
        box-shadow: 0 3px 15px rgba(0,0,0,0.18);
        font-family: Arial, sans-serif;
        text-align: center;
        min-width: 360px;
    ">
        <div style="font-size: 19px; font-weight: 700; color: #1b4332;">
            🇧🇷 Mapa Interativo do Brasil
        </div>
        <div style="margin-top: 4px; font-size: 12px; color: #555;">
            Passe a seta do mouse sobre uma unidade federativa
            para ver estado, sigla e população.
        </div>
    </div>
    """

    mapa.get_root().html.add_child(folium.Element(painel))

    # Controle simples de camadas.
    folium.LayerControl(collapsed=False).add_to(mapa)

    return mapa


def main() -> None:
    """Ponto de entrada do programa."""
    print("=" * 62)
    print("  MAPA INTERATIVO DO BRASIL - 26 ESTADOS + DF")
    print("=" * 62)

    try:
        geojson = baixar_malha()
        geojson = enriquecer_geojson(geojson)
        mapa = criar_mapa(geojson)

        arquivo_saida = Path(__file__).with_name("mapa_brasil_interativo.html")
        mapa.save(arquivo_saida)

        print(f"\nMapa gerado com sucesso:")
        print(arquivo_saida)
        print("\nAbrindo no navegador padrão...")

        webbrowser.open(arquivo_saida.resolve().as_uri())

    except Exception as erro:
        print("\nERRO:")
        print(erro)

        input(
            "\nPressione ENTER para fechar..."
        )


if __name__ == "__main__":
    main()
