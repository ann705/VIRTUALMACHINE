
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
    """Extrae servicios BLS específicos y el SUBTOTAL GENERAL"""
    servicios = []
    subtotal_general = "No encontrado"
    
    print("=== BUSCANDO SERVICIOS BLS Y SUBTOTAL ===")
    
    # Buscar SOLO códigos BLS específicos (BLS0152, BLS0291, etc.)
    patron_servicios_bls = r'(BLS\d{4})\s+(.+?)\s+\$\s*([\d\.,]+)\s*\$\s*([\d\.,]+)'
    servicios_encontrados = re.findall(patron_servicios_bls, texto)
    
    for servicio in servicios_encontrados:
        codigo = servicio[0]
        descripcion = servicio[1].strip()
        valor_unitario = servicio[2]
        subtotal_dolar = servicio[3]
        
        servicios.append({
            'CODIGO_SERVICIO': codigo,
            'DESCRIPCION': descripcion,
            'CANTIDAD': '1',
            'VALOR_UNITARIO': f"${valor_unitario}",
            'SUBTOTAL_DOLAR': f"${subtotal_dolar}",
            'SUBTOTAL': f"${valor_unitario}"
        })
        print(f"✅ Servicio BLS encontrado: {codigo} - {descripcion}")
    
    # BUSCAR SUBTOTAL - VOLVEMOS AL PATRÓN QUE SÍ FUNCIONABA
    patron_subtotal = r'SUBTOTAL\s*[\:\-]?\s*\$\s*([\d\.,]+)'
    coincidencia = re.search(patron_subtotal, texto, re.IGNORECASE)
    
    if coincidencia:
        subtotal_general = f"${coincidencia.group(1)}"
        print(f"✅ SUBTOTAL ENCONTRADO: {subtotal_general}")
    else:
        # Buscar en líneas que contengan SUBTOTAL
        lineas = texto.split('\n')
        for linea in lineas:
            if 'SUBTOTAL' in linea.upper():
                print(f"📄 Línea con SUBTOTAL: {linea}")
                numeros = re.findall(r'\$\s*([\d\.,]+)', linea)
                if numeros:
                    subtotal_general = f"${numeros[-1]}"
                    print(f"💰 Subtotal extraído: {subtotal_general}")
                    break
    
    print(f"📊 Servicios BLS encontrados: {len(servicios)}")
    print(f"💰 Subtotal general: {subtotal_general}")
    
    return servicios, subtotal_general

def extraer_datos_completos_factura(pdf_path):
    """
    Extrae todos los datos de las 3 páginas del PDF
    """
    datos_completos = {
        'informacion_general': {},
        'impuestos': {},
        'servicios': [],
        'subtotal_general': ''
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
                print("=== TEXTO PÁGINA 3 ===")
                print(texto_pagina3)
                print("======================")
                servicios, subtotal_general = extraer_servicios_pagina3(texto_pagina3)
                datos_completos['servicios'] = servicios
                datos_completos['subtotal_general'] = subtotal_general
    
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
            subtotal_general = datos_factura['subtotal_general']
            
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

                
                # AGREGAR FILA CON EL SUBTOTAL GENERAL
                fila_subtotal_general = {
                    'FACTURA_ELECTRONICA': '',
                    'FECHA_CORTE_NOVEDADES': '',
                    'TOTAL_A_PAGAR': '',
                    'TOTAL_IVA': '',
                    'TOTAL_RETE_ICA': '',
                    'CODIGO_SERVICIO': 'SUBTOTAL',
                    'DESCRIPCION': 'Total general de todos los servicios',
                    'CANTIDAD': '',
                    'VALOR_UNITARIO': '',
                    'SUBTOTAL_DOLAR': subtotal_general
                }
                filas_data.append(fila_subtotal_general)
                
            else:
                # Si no hay servicios, crear una fila solo con la información general
                fila = {
                    'FACTURA_ELECTRONICA': info_general.get('FACTURA_ELECTRONICA', 'No encontrado'),
                    'FECHA_CORTE_NOVEDADES': info_general.get('FECHA_CORTE_NOVEDADES', 'No encontrado'),
                    'TOTAL_A_PAGAR': info_general.get('TOTAL_A_PAGAR', 'No encontrado'),
                    'TOTAL_IVA': impuestos.get('TOTAL_IVA', 'No encontrado'),
                    'TOTAL_RETE_ICA': impuestos.get('TOTAL_RETE_ICA', 'No encontrado'),
                    'CODIGO_SERVICIO': 'No hay servicios',
                    'DESCRIPCION': 'No hay servicios detectados en el PDF',
                    'CANTIDAD': '',
                    'VALOR_UNITARIO': '',
                    'SUBTOTAL_DOLAR': subtotal_general
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
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)