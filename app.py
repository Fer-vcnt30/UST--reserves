from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import psycopg2
import psycopg2.extras
from datetime import date

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservas (
            id TEXT PRIMARY KEY,
            sala INTEGER NOT NULL,
            hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            integrantes TEXT,
            integrantes_detalle TEXT,
            integrantes_data JSONB,
            fecha DATE NOT NULL DEFAULT CURRENT_DATE,
            creada_en TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# ─── RUTAS ────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"status": "UST Reservas API activa ✅"})

@app.route("/reservas", methods=["GET"])
def get_reservas():
    """Devuelve todas las reservas de HOY."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM reservas WHERE fecha = %s", (date.today(),))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for r in rows:
        row = dict(r)
        row["fecha"] = str(row["fecha"])
        row["creada_en"] = str(row["creada_en"])
        result.append(row)
    return jsonify(result)

@app.route("/reservas", methods=["POST"])
def crear_reserva():
    """Crea una nueva reserva."""
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    # Verificar que no exista ya esa sala+hora hoy
    cur.execute(
        "SELECT id FROM reservas WHERE sala=%s AND hora=%s AND fecha=%s",
        (data["sala"], data["hora"], date.today())
    )
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({"error": "Ese bloque ya fue reservado."}), 409

    cur.execute("""
        INSERT INTO reservas (id, sala, hora, usuario, integrantes, integrantes_detalle, integrantes_data, fecha)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        data["id"],
        data["sala"],
        data["hora"],
        data["usuario"],
        data.get("integrantes", ""),
        data.get("integrantesDetalle", ""),
        psycopg2.extras.Json(data.get("integrantesData", [])),
        date.today()
    ))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"ok": True}), 201

@app.route("/reservas/<reserva_id>", methods=["DELETE"])
def eliminar_reserva(reserva_id):
    """Elimina una reserva por ID."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM reservas WHERE id=%s", (reserva_id,))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
