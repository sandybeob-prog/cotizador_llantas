import streamlit as st
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Cargar variables de entorno
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Validación básica
if not DATABASE_URL:
    st.error("❌ No se encontró DATABASE_URL en el archivo .env")
    st.stop()

# Conexión a la BD
engine = create_engine(DATABASE_URL)

st.title("🛞 Cotizador de Llantas")

st.subheader("Nueva cotización")

with st.form("cotizacion_form"):
    cotizador = st.text_input("Cotizador")
    cliente = st.text_input("Cliente")
    producto = st.text_input("Producto")
    cantidad = st.number_input("Cantidad", min_value=1, step=1)
    precio_unitario = st.number_input("Precio unitario", min_value=0.0, step=0.1)

    submitted = st.form_submit_button("Guardar cotización")

    if submitted:
        total = cantidad * precio_unitario

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

        with engine.connect() as conn:
            conn.execute(insert_sql, {
                "cotizador": cotizador,
                "cliente": cliente,
                "producto": producto,
                "cantidad": cantidad,
                "precio_unitario": precio_unitario,
                "total": total
            })
            conn.commit()

        st.success(f"✅ Cotización guardada. Total: S/ {total:.2f}")
