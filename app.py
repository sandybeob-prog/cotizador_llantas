import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# =========================
# Config
# =========================
load_dotenv()

st.set_page_config(page_title="Cotizador de Llantas", layout="wide")

URL_BASE_DE_DATOS = os.getenv("URL_BASE_DE_DATOS")
if not URL_BASE_DE_DATOS:
    st.error("❌ Falta la variable de entorno URL_BASE_DE_DATOS (revisa tu .env o Railway Variables).")
    st.stop()

engine = create_engine(URL_BASE_DE_DATOS, pool_pre_ping=True)

# Carpeta correcta (respeta mayúsculas/minúsculas según tu repo)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "proveedores"


# =========================
# BD: tabla (opcional pero recomendado)
# =========================
def asegurar_tabla():
    create_sql = """
    CREATE TABLE IF NOT EXISTS cotizaciones (
        id SERIAL PRIMARY KEY,
        cotizador TEXT,
        cliente TEXT,
        producto TEXT,
        cantidad INTEGER,
        precio_unitario NUMERIC,
        total NUMERIC,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """
    try:
        with engine.connect() as conn:
            conn.execute(text(create_sql))
            conn.commit()
    except Exception as e:
        st.warning(f"⚠️ No se pudo asegurar la tabla 'cotizaciones'. Detalle: {e}")


# =========================
# Cargar catálogo desde Excel
# =========================
@st.cache_data
def cargar_catalogo_productos() -> pd.DataFrame:
    archivos = sorted(DATA_DIR.glob("*.xlsx"))

    # columnas finales estándar (si no hay archivos)
    if not archivos:
        return pd.DataFrame(columns=[
            "uid", "proveedor", "uso",
            "codigo", "producto", "marca", "modelo",
            "precio", "lista_precio", "texto_busqueda", "label"
        ])

    filas = []

    # ---------- helpers ----------
    def _find_header_row(df_raw: pd.DataFrame) -> int | None:
        # busca una fila que contenga "CODIGO" en las primeras 80 filas
        top = min(len(df_raw), 80)
        for i in range(top):
            row = df_raw.iloc[i].astype(str).str.upper()
            if row.str.contains("CODIGO", na=False).any() or row.str.contains("CÓDIGO", na=False).any():
                return i
        return None

    def _norm_codigo(x) -> str:
        if pd.isna(x):
            return ""
        s = str(x).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    def col(df_cols, posibles):
        for p in posibles:
            if p in df_cols:
                return p
        return None

    # ---------- procesar cada excel ----------
    for ruta in archivos:
        proveedor = ruta.stem  # nombre archivo sin .xlsx

        try:
            # lee TODAS las hojas sin header para detectar la fila real de encabezados
            sheets = pd.read_excel(ruta, sheet_name=None, header=None)

            df_list = []

            for sheet_name, df_raw in sheets.items():
                hdr = _find_header_row(df_raw)
                if hdr is None:
                    continue

                df_tmp = df_raw.copy()
                df_tmp.columns = df_tmp.iloc[hdr]          # fila header
                df_tmp = df_tmp.iloc[hdr + 1:].copy()      # datos debajo del header

                # normalizar nombres columnas
                df_tmp.columns = [str(c).strip().lower() for c in df_tmp.columns]

                # ✅ FIX MÍNIMO: quitar columnas duplicadas (COMERCIO suele traer encabezados repetidos)
                df_tmp = df_tmp.loc[:, ~pd.Index(df_tmp.columns).duplicated(keep="first")]

                # eliminar filas totalmente vacías
                df_tmp = df_tmp.dropna(how="all")

                # guardar el "uso" como nombre de hoja (TBR/TBB/OTR/PCR/etc.)
                df_tmp["_uso"] = str(sheet_name).strip().upper()

                df_list.append(df_tmp)

            # ✅ NO meter "filas ERROR" al catálogo
            if not df_list:
                st.warning(f"⚠️ {proveedor}: no se encontró encabezado con CODIGO en ninguna hoja.")
                continue

            df = pd.concat(df_list, ignore_index=True)

            # --------- mapeo flexible ----------
            mapa = {
                "codigo": ["codigo", "código", "cod", "sku", "cod."],
                "producto": ["producto", "descripcion", "descripción", "medida", "llanta", "medida/tamaño", "medida tamaño"],
                "marca": ["marca"],
                "modelo": ["modelo"],
                "precio": ["precio", "contado", "contado dist", "lima premium", "precio unit", "precio_unit", "p.unit", "p_unit", "unitario"],
                "lista_precio": ["lista_precio", "lista precio", "tarifa", "lista", "crédito", "credito", "credito dist", "crédito dist"],
            }

            c_codigo = col(df.columns, mapa["codigo"])
            c_producto = col(df.columns, mapa["producto"])
            c_marca = col(df.columns, mapa["marca"])
            c_modelo = col(df.columns, mapa["modelo"])
            c_precio = col(df.columns, mapa["precio"])
            c_lista = col(df.columns, mapa["lista_precio"])

            # construir dataframe estándar
            out = pd.DataFrame({
                "proveedor": [proveedor] * len(df),
                "uso": df["_uso"].astype(str),
                "codigo": df[c_codigo].map(_norm_codigo) if c_codigo else [""] * len(df),
                "producto": df[c_producto].fillna("").astype(str) if c_producto else [""] * len(df),
                "marca": df[c_marca].fillna("").astype(str) if c_marca else [""] * len(df),
                "modelo": df[c_modelo].fillna("").astype(str) if c_modelo else [""] * len(df),
                "precio": df[c_precio] if c_precio else [None] * len(df),
                "lista_precio": df[c_lista].fillna("").astype(str) if c_lista else [""] * len(df),
            })

            # precio a número (si viene con $ o texto, lo fuerza)
            out["precio"] = pd.to_numeric(out["precio"], errors="coerce")

            # uid único
            out = out.reset_index(drop=True)
            out["uid"] = (
                out["proveedor"].astype(str) + "|" +
                out["uso"].astype(str) + "|" +
                out.index.astype(str)
            )

            # texto búsqueda (como Excel)
            out["texto_busqueda"] = (
                out["codigo"].fillna("").astype(str).str.upper() + " " +
                out["producto"].fillna("").astype(str).str.upper() + " " +
                out["marca"].fillna("").astype(str).str.upper() + " " +
                out["modelo"].fillna("").astype(str).str.upper()
            ).str.replace(r"\s+", " ", regex=True).str.strip()

            # label visible en el selectbox
            out["label"] = (
                out["marca"].fillna("").astype(str).str.upper() +
                " | " + out["uso"].fillna("").astype(str) +
                " | S/ " + out["precio"].fillna(0).map(lambda x: f"{x:.2f}")
            )

            filas.append(out)

        except Exception as e:
            # ✅ NO meter fila ERROR al catálogo
            st.error(f"❌ ERROR leyendo {proveedor}: {e}")
            continue

    if not filas:
        return pd.DataFrame(columns=[
            "uid", "proveedor", "uso",
            "codigo", "producto", "marca", "modelo",
            "precio", "lista_precio", "texto_busqueda", "label"
        ])

    catalogo = pd.concat(filas, ignore_index=True)
    return catalogo


# =========================
# UI
# =========================
st.title("🛞 Cotizador de Llantas")
st.subheader("Nueva cotización")

asegurar_tabla()

catalogo = cargar_catalogo_productos()

with st.expander("📦 Catálogo de productos (búsqueda tipo Excel)", expanded=True):
    if catalogo.empty:
        st.error("No se encontraron productos válidos. Revisa que los Excel existan y tengan encabezado con CODIGO.")
        st.stop()

    busqueda = st.text_input(
        "Buscar (ej: R12, 16.9 38, PCR1200, 155/70, AEOLUS, etc.)",
        placeholder="Escribe como en el filtro de Excel...",
        key="busqueda_excel"
    )

    filtrados = catalogo
    if busqueda.strip():
        b = busqueda.strip().upper()
        filtrados = catalogo[catalogo["texto_busqueda"].str.contains(b, na=False)]

    st.caption(f"Resultados: {len(filtrados)}")

    # ✅ UNA SOLA TABLA (como antes)
    cols_tabla = ["proveedor", "codigo", "producto", "marca", "modelo", "uso", "precio", "lista_precio"]
    cols_tabla_ok = [c for c in cols_tabla if c in filtrados.columns]
    st.dataframe(filtrados[cols_tabla_ok], use_container_width=True, height=320)

    if filtrados.empty:
        st.warning("No hay coincidencias con esa búsqueda.")
        st.stop()


# =========================
# Selección segura (UN SOLO SELECTBOX)
# =========================
if "uid" not in filtrados.columns or "label" not in filtrados.columns:
    st.error("Faltan columnas uid/label. Revisa cargar_catalogo_productos().")
    st.stop()

uid_to_label = dict(zip(filtrados["uid"].astype(str), filtrados["label"].astype(str)))
opciones_uid = filtrados["uid"].astype(str).tolist()

uid_seleccionado = st.selectbox(
    "Selecciona el producto de la lista filtrada",
    options=opciones_uid,
    format_func=lambda u: uid_to_label.get(u, u),
    key="select_producto_uid"
)

df_sel = filtrados[filtrados["uid"].astype(str) == str(uid_seleccionado)]
if df_sel.empty:
    st.warning("No se encontró el producto seleccionado.")
    st.stop()

fila_sel = df_sel.iloc[0]
producto_final = str(fila_sel.get("label", ""))
precio_sugerido = float(fila_sel.get("precio") or 0.0)


# =========================
# Formulario de cotización
# =========================
st.markdown("### 🧾 Formulario de cotización")

with st.form("cotizacion_form"):
    cotizador = st.text_input("Cotizador")
    cliente = st.text_input("Cliente")
    producto = st.text_input("Producto", value=producto_final)

    cantidad = st.number_input("Cantidad", min_value=1, step=1, value=1)
    precio_unitario = st.number_input("Precio unitario", min_value=0.0, step=0.1, value=float(precio_sugerido))

    submitted = st.form_submit_button("Guardar cotización")

if submitted:
    total = float(cantidad) * float(precio_unitario)

    insert_sql = text("""
        INSERT INTO cotizaciones (
            cotizador,
            cliente,
            producto,
            cantidad,
            precio_unitario,
            total
        )
        VALUES (
            :cotizador,
            :cliente,
            :producto,
            :cantidad,
            :precio_unitario,
            :total
        )
    """)

    try:
        with engine.connect() as conn:
            conn.execute(insert_sql, {
                "cotizador": cotizador,
                "cliente": cliente,
                "producto": producto,
                "cantidad": int(cantidad),
                "precio_unitario": float(precio_unitario),
                "total": float(total),
            })
            conn.commit()

        st.success(f"✅ Cotización guardada. Total: S/ {total:.2f}")

    except Exception as e:
        st.error(f"❌ No se pudo guardar la cotización. Detalle: {e}")
