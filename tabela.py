import streamlit as st
import numpy as np
import pandas as pd
import requests
from requests.exceptions import RequestException
from st_aggrid import AgGrid, GridOptionsBuilder
from requests.auth import HTTPBasicAuth
import base64
import json
from pathlib import Path
from datetime import date
import io
import pdfplumber
import pyodbc
import re
from datetime import datetime, timedelta

# state para armazenar data da última atualização
if "ultima_atualizacao" not in st.session_state:
    st.session_state.ultima_atualizacao = None
if "carregou_uma_vez" not in st.session_state:
    st.session_state.carregou_uma_vez = True
    st.cache_data.clear()
    st.session_state.ultima_atualizacao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")


# botão de atualizar (limpa cache e recarrega)
def atualizar_dados():
    st.cache_data.clear()
    st.session_state.ultima_atualizacao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    st.rerun()

# config inicial da pág
st.set_page_config(page_title="Consulta Tabelas de Preço", layout="wide")
st.title("Consulta Tabelas de Preço")

cols = st.columns([6, 2])

with cols[1]:
    if st.button("🔄 Atualizar dados"):
        atualizar_dados()

# Mostra a data da última atualização
if st.session_state.ultima_atualizacao:
    cols[1].markdown(
        f"<p style='font-size:12px; color:gray; text-align:right;'>"
        f"Última atualização:<br><strong>{st.session_state.ultima_atualizacao}</strong></p>",
        unsafe_allow_html=True
    )
else:
    cols[1].markdown(
        "<p style='font-size:12px; color:gray; text-align:right;'>"
        "Dados ainda não foram atualizados manualmente</p>",
        unsafe_allow_html=True
    )


# obter tabelas de preço
@st.cache_data
def obter_tabelas():
    try:
        url = "http://ambartech134415.protheus.cloudtotvs.com.br:1807/rest/api/v1/calccomponentesorc2022/tabelapreco"
        response = requests.get(url, auth=HTTPBasicAuth("ambar.integracao", "!ambar@2025int"))
        response.raise_for_status()

        dados_api = response.json()
        df_tab = pd.DataFrame(dados_api)

        df_tab["DA1_CODPRO"] = df_tab["DA1_CODPRO"].astype(str).str.zfill(6)
        #converte para valor numerico
        #df_tab["B1_IPI"] = pd.to_numeric(df_tab["B1_IPI"], errors='coerce')
        #df_tab["B1_IPI"] = df_tab["B1_IPI"].fillna(0)
        df_tab = df_tab[["DA1_CODPRO", "B1_DESC", "DA0_DESCRI", "DA1_CODTAB", "DA1_PRCVEN", "DA0_CONDPG", "B1_IPI"]]
        df_tab.rename(columns={"DA1_CODPRO": "Código do Produto", "B1_DESC": "Descrição Produto", "DA0_DESCRI": "Descrição Tabela", "DA1_CODTAB": "Código Tabela", "DA1_PRCVEN": "Preço", "DA0_CONDPG": "Condição de Pagamento", "B1_IPI": "IPI"}, inplace=True)
        return df_tab
    except RequestException as e:
        st.error(f"Erro ao obter dados da API: {e}")
        #st.session_state.ultima_atualizacao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return pd.DataFrame(columns=["Código do Produto", "Descrição Produto", "IPI", "NCM", "Descrição Tabela", "Código Tabela", "Preço"])
df_tabelas_preco = obter_tabelas()

@st.cache_data
def obter_condicoes_pagamento():
    try:
        url = "http://ambartech134415.protheus.cloudtotvs.com.br:1807/rest/api/v1/calccomponentesorc2022/se4"
        response = requests.get(url, auth=HTTPBasicAuth("ambar.integracao", "!ambar@2025int"))
        response.raise_for_status()

        dados_api = response.json()
        df_cond = pd.DataFrame(dados_api)

        df_cond = df_cond[["E4_CODIGO", "E4_DESCRI", "E4_XACRESC"]]
        df_cond.rename(columns={"E4_CODIGO": "Condição de Pagamento", "E4_DESCRI": "Descrição Condição", "E4_XACRESC": "% Juros"}, inplace=True)

        # importante: garantir que os tipos batem com o dataframe principal
        df_cond["Condição de Pagamento"] = df_cond["Condição de Pagamento"].astype(str)
        #st.session_state.ultima_atualizacao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return df_cond

    except RequestException as e:
        st.error(f"Erro ao obter condições de pagamento: {e}")
        return pd.DataFrame(columns=["Condição de Pagamento", "Descrição Condição"])
df_condicoes = obter_condicoes_pagamento()


if not df_tabelas_preco.empty:
    df_tabelas_preco["Condição de Pagamento"] = df_tabelas_preco["Condição de Pagamento"].astype(str)

    # cria uma lista única com "Código - Descrição"
    df_listagem = (
        df_tabelas_preco[["Código Tabela", "Descrição Tabela"]]
        .drop_duplicates()
        .sort_values("Código Tabela")
    )

    df_listagem["Tabela"] = df_listagem["Código Tabela"].astype(str) + " - " + df_listagem["Descrição Tabela"]

    # juntar com a SE4
    df_tabelas_preco = df_tabelas_preco.merge(
        df_condicoes,
        on="Condição de Pagamento",
        how="left"
    )
    df_tabelas_preco["% Juros"] = pd.to_numeric(df_tabelas_preco["% Juros"], errors="coerce").fillna(0)
    df_tabelas_preco["Preço"] = pd.to_numeric(df_tabelas_preco["Preço"], errors="coerce").fillna(0)
    df_tabelas_preco["IPI"] = pd.to_numeric(df_tabelas_preco["IPI"], errors="coerce").fillna(0)
    df_tabelas_preco["Preço TOTVS sem IPI"] = df_tabelas_preco["Preço"] * (1 + df_tabelas_preco["% Juros"] / 100)
    df_tabelas_preco["Preço TOTVS sem IPI"] = np.ceil(df_tabelas_preco["Preço TOTVS sem IPI"] * 100) / 100

    df_tabelas_preco["Preço TOTVS com IPI"] = df_tabelas_preco["Preço TOTVS sem IPI"] * (1 + df_tabelas_preco["IPI"] / 100)
    df_tabelas_preco["Preço TOTVS com IPI"] = np.ceil(df_tabelas_preco["Preço TOTVS com IPI"] * 100) / 100

    df_tabelas_preco["Condição de Pagamento"] = (
        df_tabelas_preco["Condição de Pagamento"].astype(str) 
        + " - " 
        + df_tabelas_preco["Descrição Condição"].fillna("")
    )


    df_tabelas_preco = df_tabelas_preco.drop(columns=["Descrição Condição"])
    df_tabelas_preco = df_tabelas_preco.drop(columns=["Preço"])
    df_tabelas_preco = df_tabelas_preco.drop(columns=["% Juros"])

    with st.container():
        st.markdown("### 🔍 Filtros")
        tabela_escolhida = st.selectbox("Selecione a Tabela de Preço:", df_listagem["Tabela"].tolist(), index=None,placeholder="Digite ou selecione uma tabela...")

        df_filtrado = df_tabelas_preco.copy()

        # Extrair apenas o código da tabela selecionada
        #cod_tabela_selecionado = tabela_escolhida.split(" - ")[0]
        if tabela_escolhida:
            cod_tabela_selecionado = tabela_escolhida.split(" - ")[0]
            df_filtrado = df_filtrado[df_filtrado["Código Tabela"].astype(str) == cod_tabela_selecionado]

        # Filtrar os produtos da tabela selecionada
        #df_filtrado = df_tabelas_preco[df_tabelas_preco["Código Tabela"].astype(str) == cod_tabela_selecionado]

        #REMOVE AS COLUNAS QUE NÃO DEVEM APARECER NA TABELA FINAL
        df_filtrado = df_filtrado.drop(columns=["Código Tabela", "Descrição Tabela"])

        # Criar coluna combinada para exibição no filtro
        df_filtrado["Código + Condição"] = (
            df_filtrado["Código do Produto"].astype(str)
            + " - "
            + df_filtrado["Descrição Produto"].astype(str)
        )

        #usuario consegue filtrar varios produtos
        codigos_unicos = sorted(df_filtrado["Código + Condição"].unique())

        filtro_codigos = st.multiselect(
            "Filtrar por Código do Produto (selecione um ou vários):",
            options=codigos_unicos,
            default=[]
        )

    # aplica o filtro se o usuário selecionar algum código
    if filtro_codigos:
        df_filtrado = df_filtrado[df_filtrado["Código + Condição"].isin(filtro_codigos)]

    # Remover coluna auxiliar da tabela final
    df_filtrado = df_filtrado.drop(columns=["Código + Condição"])

    st.markdown("### 📦 Produtos da Tabela Selecionada")


    gb = GridOptionsBuilder.from_dataframe(df_filtrado)
    gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=20)
    gb.configure_default_column(editable=False, filter=True, sortable=True, resizable=True)
    gb.configure_column("IPI", width=80)
    gridOptions = gb.build()

    AgGrid(df_filtrado, gridOptions=gridOptions, height=500, fit_columns_on_grid_load=True)

else:
    st.warning("Nenhuma tabela encontrada na API.")






