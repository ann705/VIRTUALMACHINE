import os
import pandas as pd
from flask import Flask, render_template, request

app = Flask(__name__)

DATA_PATH = "data"

def get_excel_files():
    return [f for f in os.listdir(DATA_PATH) if f.lower().endswith(".xlsx")]

def load_excel(filename):
    path = os.path.join(DATA_PATH, filename)
    # lee la primera hoja por defecto; si necesitas otra hoja usa sheet_name=...
    return pd.read_excel(path)

@app.route("/", methods=["GET", "POST"])
def index():
    files = get_excel_files()
    selected_file = request.form.get("excel_file") if request.method == "POST" else (files[0] if files else None)
    search_query = request.form.get("search_query", "").strip() if request.method == "POST" else ""
    table_html = None
    info_msg = None

    app.logger.info(f"Files available: {files}")
    app.logger.info(f"Selected file: {selected_file} | Query: '{search_query}'")

    if not files:
        info_msg = "No se encontraron archivos .xlsx en la carpeta data/."
        return render_template("index.html", files=files, selected_file=selected_file, search_query=search_query, table_html=table_html, info_msg=info_msg)

    try:
        df = load_excel(selected_file)
    except Exception as e:
        app.logger.error(f"Error leyendo {selected_file}: {e}")
        info_msg = f"Error leyendo el archivo {selected_file}: {e}"
        return render_template("index.html", files=files, selected_file=selected_file, search_query=search_query, table_html=table_html, info_msg=info_msg)

    # Si hay query, filtramos en todas las columnas (búsqueda libre)
    if search_query:
        # convertimos todo a str y usamos contains con regex=False para buscar literalmente
        try:
            mask = df.astype(str).apply(lambda col: col.str.contains(search_query, case=False, na=False, regex=False)).any(axis=1)
        except TypeError:
            # fallback en caso de versiones antiguas de pandas que no acepten regex arg
            mask = df.astype(str).apply(lambda col: col.str.contains(search_query, case=False, na=False)).any(axis=1)

        filtered = df[mask]
        app.logger.info(f"Filtrado: filas antes={len(df)} después={len(filtered)}")
        df_to_show = filtered
        if len(filtered) == 0:
            info_msg = f"No se encontraron resultados para '{search_query}' en {selected_file}."
    else:
        df_to_show = df

    # convierto a HTML (bootstrap classes)
    table_html = df_to_show.to_html(classes="table table-striped table-sm", index=False, escape=False)

    return render_template("index.html",
                           files=files,
                           selected_file=selected_file,
                           search_query=search_query,
                           table_html=table_html,
                           info_msg=info_msg)

if __name__ == "__main__":
    app.run(debug=True)
