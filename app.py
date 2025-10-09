from flask import Flask, render_template, request, send_file, flash
from werkzeug.utils import secure_filename
import pandas as pd
import os
import pdfplumber
import re
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave'

# 📂 Configuración de carpetas
UPLOAD_FOLDER = "uploads"
DATA_FOLDER = os.path.join(os.getcwd(), "data")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)

# 📌 Configuración de archivos permitidos
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extraer_datos_pagina1(texto):
    """Extrae datos de la primera página"""
    datos = {}
    
    patrones_pagina1 = {
        'FACTURA_ELECTRONICA': r'FACTURA ELECTRÓNICA DE VENTA:\s*([\d\s\-\–]+)',
        'FECHA_CORTE_NOVEDADES': r'FECHA CORTE NOVEDADES:\s*([A-Za-z]+\s*\d+\/\d+)',
        'TOTAL_A_PAGAR': r'TOTAL A PAGAR:\s*([$\s]*([\d\.,]+))'
    }
    
    for campo, patron in patrones_pagina1.items():
        coincidencia = re.search(patron, texto)
        if coincidencia:
            if campo == 'TOTAL_A_PAGAR' and len(coincidencia.groups()) > 1:
                datos[campo] = f"${coincidencia.group(2)}"
            else:
                datos[campo] = coincidencia.group(1).strip()
        else:
            datos[campo] = "No encontrado"
    
    return datos

def extraer_impuestos_pagina2(texto):
    """Extrae datos de impuestos de la página 2"""
    impuestos = {}
    
    patrones_impuestos = {
        'TOTAL_IVA': r'Total IVA\s*([$\s]*([\d\.,\-]+))',
        'TOTAL_RETE_ICA': r'Total Rete ICA\s*([$\s]*([\d\.,\-]+))',
    }
    
    for impuesto, patron in patrones_impuestos.items():
        coincidencia = re.search(patron, texto)
        if coincidencia:
            if len(coincidencia.groups()) > 1:
                valor = coincidencia.group(2)
                if not valor.startswith('$'):
                    valor = f"${valor}"
                impuestos[impuesto] = valor
            else:
                impuestos[impuesto] = coincidencia.group(1).strip()
        else:
            impuestos[impuesto] = "No encontrado"
    
    return impuestos

def extraer_servicios_pagina3(texto):
    """Extrae servicios de IP DATA EXTRANET LOCAL"""
    servicios = []
    
    # Buscar líneas que contengan códigos BLS
    lineas = texto.split('\n')
    
    for linea in lineas:
        # Buscar patrones de servicios BLS
        if 'BLS' in linea:
            # Patrón para extraer código, descripción y precios
            patron = r'([A-Z]{3}\d{4})\s+(.+?)\s+(\d+)\s+\d{4}-\d{2}-\d{2}\s+\d{4}-\d{2}-\d{2}\s+\$\s*([\d\.,]+)\s+\$\s*([\d\.,]+)\s+\$\s*([\d\.,]+)'
            coincidencia = re.search(patron, linea)
            
            if coincidencia:
                servicio = {
                    'CODIGO_SERVICIO': coincidencia.group(1),
                    'DESCRIPCION': coincidencia.group(2).strip(),
                    'CANTIDAD': coincidencia.group(3),
                    'VALOR_UNITARIO': f"${coincidencia.group(4)}",
                    'SUBTOTAL_DOLAR': f"${coincidencia.group(6)}"
                }
                servicios.append(servicio)
    
    return servicios

def extraer_datos_completos_factura(pdf_path):
    """
    Extrae todos los datos de las 3 páginas del PDF
    """
    datos_completos = {
        'informacion_general': {},
        'impuestos': {},
        'servicios': []
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Página 1 - Información general
            if len(pdf.pages) > 0:
                pagina1 = pdf.pages[0]
                texto_pagina1 = pagina1.extract_text() or ""
                datos_completos['informacion_general'] = extraer_datos_pagina1(texto_pagina1)
            
            # Página 2 - Impuestos
            if len(pdf.pages) > 1:
                pagina2 = pdf.pages[1]
                texto_pagina2 = pagina2.extract_text() or ""
                datos_completos['impuestos'] = extraer_impuestos_pagina2(texto_pagina2)
            
            # Página 3 - Servicios
            if len(pdf.pages) > 2:
                pagina3 = pdf.pages[2]
                texto_pagina3 = pagina3.extract_text() or ""
                datos_completos['servicios'] = extraer_servicios_pagina3(texto_pagina3)
            
    except Exception as e:
        print(f"Error procesando PDF: {e}")
        flash(f'Error al procesar el PDF: {str(e)}', 'error')
    
    return datos_completos

def cargar_datos():
    """Lee todos los Excels de la carpeta data y los combina"""
    all_data = []
    for file in os.listdir(DATA_FOLDER):
        if file.endswith(".xlsx"):
            try:
                df = pd.read_excel(os.path.join(DATA_FOLDER, file))
                df["Archivo"] = file
                all_data.append(df)
            except Exception as e:
                print(f"Error leyendo {file}: {e}")
    
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()

# 📌 Ruta principal
@app.route("/")
def home():
    return render_template("home.html")

# 📄 Procesar PDF
@app.route("/upload-pdf", methods=["GET", "POST"])
def upload_pdf():
    if request.method == "POST":
        if 'pdf' not in request.files:
            flash('No se seleccionó ningún archivo', 'error')
            return render_template("upload_pdf.html")

        file = request.files['pdf']
        if file.filename == '':
            flash('No se seleccionó ningún archivo', 'error')
            return render_template("upload_pdf.html")

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)

            # Extraer datos del PDF
            datos_factura = extraer_datos_completos_factura(filepath)

            # Crear TABLA con múltiples filas
            filas_data = []
            
            info_general = datos_factura['informacion_general']
            impuestos = datos_factura['impuestos']
            servicios = datos_factura['servicios']
            
            # Si hay servicios, crear una fila por cada servicio
            if servicios:
                for servicio in servicios:
                    fila = {
                        'FACTURA_ELECTRONICA': info_general.get('FACTURA_ELECTRONICA', 'No encontrado'),
                        'FECHA_CORTE_NOVEDADES': info_general.get('FECHA_CORTE_NOVEDADES', 'No encontrado'),
                        'TOTAL_A_PAGAR': info_general.get('TOTAL_A_PAGAR', 'No encontrado'),
                        'TOTAL_IVA': impuestos.get('TOTAL_IVA', 'No encontrado'),
                        'TOTAL_RETE_ICA': impuestos.get('TOTAL_RETE_ICA', 'No encontrado'),
                        'CODIGO_SERVICIO': servicio.get('CODIGO_SERVICIO', ''),
                        'DESCRIPCION': servicio.get('DESCRIPCION', ''),
                        'CANTIDAD': servicio.get('CANTIDAD', ''),
                        'VALOR_UNITARIO': servicio.get('VALOR_UNITARIO', ''),
                        'SUBTOTAL_DOLAR': servicio.get('SUBTOTAL_DOLAR', '')
                    }
                    filas_data.append(fila)
            else:
                # Si no hay servicios, crear una fila solo con la información general
                fila = {
                    'FACTURA_ELECTRONICA': info_general.get('FACTURA_ELECTRONICA', 'No encontrado'),
                    'FECHA_CORTE_NOVEDADES': info_general.get('FECHA_CORTE_NOVEDADES', 'No encontrado'),
                    'TOTAL_A_PAGAR': info_general.get('TOTAL_A_PAGAR', 'No encontrado'),
                    'TOTAL_IVA': impuestos.get('TOTAL_IVA', 'No encontrado'),
                    'TOTAL_RETE_ICA': impuestos.get('TOTAL_RETE_ICA', 'No encontrado'),
                    'CODIGO_SERVICIO': 'No hay servicios',
                    'DESCRIPCION': 'No hay servicios',
                    'CANTIDAD': '',
                    'VALOR_UNITARIO': '',
                    'SUBTOTAL_DOLAR': ''
                }
                filas_data.append(fila)

            df_final = pd.DataFrame(filas_data)

            if not df_final.empty:
                excel_path = os.path.join(UPLOAD_FOLDER, f"factura_resumen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                
                # Guardar en una sola tabla
                with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                    df_final.to_excel(writer, sheet_name="Resumen_Factura", index=False)
                
                flash('✅ Datos extraídos exitosamente en una tabla', 'success')
                return send_file(excel_path, as_attachment=True)
            else:
                flash('⚠️ No se encontraron datos válidos en el PDF', 'error')

    return render_template("upload_pdf.html")

# 📊 Consulta de VMs
@app.route("/consulta-vm", methods=["GET", "POST"])
def consulta_vm():
    query = None
    periodo = None
    resumen = None
    mostrar_botones = False

    if request.method == "POST":
        query = request.form.get("query")
        periodo = request.form.get("periodo")
        df = cargar_datos()

        if not df.empty and query:
            df_vm = df[df.apply(lambda row: row.astype(str).str.contains(query, case=False).any(), axis=1)]
            
            if not df_vm.empty:
                mostrar_botones = True

                if periodo:
                    columnas = [c for c in df_vm.columns if "CPU" in c or "Mem" in c or "Disk" in c]
                    df_metrics = df_vm[columnas]
                    promedios = df_metrics.mean(numeric_only=True)

                    resumen = promedios.reset_index()
                    resumen.columns = ["Métrica", "Promedio"]
                    resumen = resumen.to_html(classes="table table-bordered", index=False)

    return render_template("index.html", query=query, mostrar_botones=mostrar_botones, resumen=resumen, periodo=periodo)

# 🚀 Arranque del servidor
if __name__ == "__main__":
    app.run(debug=True)