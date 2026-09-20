#!/usr/bin/env python3
"""
Heinäautomaatti - releiden ja piezo-summerin vuorokausiohjaus.

- Ohjaa releitä (tuki 8 hyllylle)
- Piippaa aktiivisella piezolla ennen releen aktivointia
- Vuorokausiajastin (samat ajat joka päivä), aikavyöhyke = järjestelmän paikallinen aika
- Web-käyttöliittymä (Flask) ajastusten muokkaukseen, manuaaliseen testaukseen ja lokin lukuun
- Asetukset tallennetaan config.json-tiedostoon

Releet: GPIO.LOW = rele vetää (aktiivi-LOW relemoduuli)
Piezo: GPIO.HIGH = piippaa

Hyllyn näkyvyys web-UI:ssa:
  config.json:ssa kenttä "visible": true/false per hylly.
  visible=false  -> hylly piilotettu UI:sta, mutta ajastin ja GPIO toimivat
                    normaalisti jos enabled=true.
  visible=true   -> hylly näkyy UI:ssa ja on muokattavissa.
  Muuta visible-arvo config.json:ssa tekstieditorilla tai suoraan tiedostoon;
  skripti lukee arvon käynnistyessä ja tallennuksen yhteydessä.
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, request, redirect, url_for, render_template_string
from waitress import serve

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    # Mahdollistaa testaamisen koneella, jossa ei ole RPi.GPIO:ta
    GPIO_AVAILABLE = False

# ---------------------------------------------------------------------------
# Polut ja vakiot
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "tapahtumat.log")

WEB_HOST = "0.0.0.0"
WEB_PORT = 8080

# ---------------------------------------------------------------------------
# Lokitus
# ---------------------------------------------------------------------------

_log_lock = threading.Lock()


def log_event(message: str) -> None:
    """Kirjoittaa aikaleimatun rivin lokitiedostoon ja tulostaa sen konsoliin."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} - {message}"
    print(line, flush=True)
    with _log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            print(f"Lokin kirjoitus epäonnistui: {exc}", flush=True)


def read_log() -> str:
    with _log_lock:
        if not os.path.exists(LOG_FILE):
            return ""
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Uusin rivi ylimpänä
        return "".join(reversed(lines))


def clear_log() -> None:
    with _log_lock:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
    log_event("Loki tyhjennetty käyttäjän toimesta.")


# ---------------------------------------------------------------------------
# Konfiguraation hallinta
# ---------------------------------------------------------------------------

_config_lock = threading.Lock()
_config = {}

# Seuraa, onko jokin hylly jo lauennut tänä päivänä (estää toiston samana
# vuorokautena, jos sekuntiosuma "ajaa" useammin kuin kerran)
_last_run_date = {}


def load_config() -> dict:
    with _config_lock:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)


def save_config(cfg: dict) -> None:
    with _config_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_config() -> dict:
    global _config
    with _config_lock:
        return json.loads(json.dumps(_config))  # syvä kopio


def set_config(cfg: dict) -> None:
    global _config
    with _config_lock:
        _config = cfg
    save_config(cfg)


# ---------------------------------------------------------------------------
# GPIO-ohjaus
# ---------------------------------------------------------------------------

_gpio_lock = threading.Lock()
_initialized_pins = set()


def gpio_setup():
    if not GPIO_AVAILABLE:
        log_event("VAROITUS: RPi.GPIO ei ole käytettävissä - simulointitila.")
        return

    GPIO.setmode(GPIO.BCM)
    cfg = get_config()

    # Alustetaan kaikki pinnit, myös piilotettujen hyllyjen (visible=false)
    pins = [cfg["buzzer_pin"]]
    for shelf in cfg["shelves"].values():
        pins.append(shelf["pin"])

    for pin in pins:
        if pin in _initialized_pins:
            continue
        GPIO.setup(pin, GPIO.OUT)
        _initialized_pins.add(pin)

    # Releet: HIGH = lepotila (ei vedä), LOW = vetää
    for shelf in cfg["shelves"].values():
        GPIO.output(shelf["pin"], GPIO.HIGH)

    # Piezo: LOW = ei piippaa
    GPIO.output(cfg["buzzer_pin"], GPIO.LOW)


def gpio_cleanup():
    if GPIO_AVAILABLE:
        GPIO.cleanup()


def relay_set(pin: int, active: bool) -> None:
    """active=True -> rele vetää (GPIO LOW), active=False -> lepotila (HIGH)"""
    if not GPIO_AVAILABLE:
        return
    GPIO.output(pin, GPIO.LOW if active else GPIO.HIGH)


def buzzer_set(pin: int, on: bool) -> None:
    if not GPIO_AVAILABLE:
        return
    GPIO.output(pin, GPIO.HIGH if on else GPIO.LOW)


# ---------------------------------------------------------------------------
# Hyllyn avaussekvenssi: piippaukset + rele
# ---------------------------------------------------------------------------

def run_shelf_sequence(shelf_key: str) -> None:
    """
    Suorittaa täyden sekvenssin yhdelle hyllylle:
    N x (piippaus + tauko) -> rele vetää relay_active_seconds ajan -> rele pois
    Tämä funktio on suunniteltu ajettavaksi omassa säikeessään.
    """
    cfg = get_config()
    shelf = cfg["shelves"].get(shelf_key)
    if shelf is None or not shelf.get("enabled", True):
        return

    name = shelf["name"]
    pin = shelf["pin"]
    buzzer_pin = cfg["buzzer_pin"]
    beep_count = cfg.get("beep_count", 5)
    beep_on = cfg.get("beep_on_seconds", 1)
    beep_off = cfg.get("beep_off_seconds", 1)
    relay_seconds = cfg.get("relay_active_seconds", 2)

    with _gpio_lock:
        log_event(f"Sekvenssi alkaa: {name} (pinni {pin}) - piippaukset alkavat.")

        for i in range(beep_count):
            buzzer_set(buzzer_pin, True)
            time.sleep(beep_on)
            buzzer_set(buzzer_pin, False)
            time.sleep(beep_off)

        log_event(f"Rele vetää: {name} (pinni {pin}) {relay_seconds}s.")
        relay_set(pin, True)
        time.sleep(relay_seconds)
        relay_set(pin, False)
        log_event(f"Rele palautui lepotilaan: {name} (pinni {pin}).")
        log_event(f"Sekvenssi valmis: {name}.")


def trigger_shelf_async(shelf_key: str, manual: bool = False) -> None:
    if manual:
        log_event(f"Manuaalinen aukaisu: {shelf_key}")
    t = threading.Thread(target=run_shelf_sequence, args=(shelf_key,), daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Ajastinsäie — käy läpi KAIKKI hyllyt riippumatta visible-kentästä
# ---------------------------------------------------------------------------

def parse_hhmm(value: str):
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return None


def scheduler_loop(stop_event: threading.Event):
    log_event("Ajastinsäie käynnistyi.")
    while not stop_event.is_set():
        now = datetime.now()
        cfg = get_config()
        lead = cfg.get("buzzer_lead_seconds", 10)
        today_str = now.strftime("%Y-%m-%d")

        for shelf_key, shelf in cfg["shelves"].items():
            # visible-kenttä ei vaikuta ajastimeen — ainoastaan enabled ratkaisee
            if not shelf.get("enabled", True):
                continue

            hhmm = parse_hhmm(shelf.get("time", ""))
            if hhmm is None:
                continue

            h, m = hhmm
            target_open = now.replace(hour=h, minute=m, second=0, microsecond=0)
            trigger_time = target_open - timedelta(seconds=lead)

            already_run = _last_run_date.get(shelf_key) == today_str

            if (not already_run
                    and now.hour == trigger_time.hour
                    and now.minute == trigger_time.minute
                    and now.second == trigger_time.second):
                _last_run_date[shelf_key] = today_str
                log_event(
                    f"Ajastettu aukaisu: {shelf['name']} "
                    f"(avautuminen klo {shelf['time']}, piippaukset alkavat nyt)."
                )
                trigger_shelf_async(shelf_key, manual=False)

        time.sleep(0.5)

    log_event("Ajastinsäie pysähtyi.")


# ---------------------------------------------------------------------------
# Flask-web-käyttöliittymä
# ---------------------------------------------------------------------------

app = Flask(__name__)

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Heinäautomaatti</title>
  <style>
    body { font-family: sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; background:#f7f7f5; color:#222;}
    h1 { margin-bottom: 0.2rem; }
    .card { background: white; border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1);}
    table { width: 100%; border-collapse: collapse; }
    td, th { padding: 0.5rem; text-align: left; border-bottom: 1px solid #eee; }
    input[type=time] { font-size: 1rem; padding: 0.2rem; }
    input[type=number] { width: 4rem; }
    .btn { background:#3a6b35; color:white; border:none; padding:0.5rem 1rem; border-radius:5px; cursor:pointer; font-size:0.95rem;}
    .btn:hover { background:#2e5429; }
    .btn-danger { background:#a13b3b; }
    .btn-danger:hover { background:#822f2f; }
    .btn-secondary { background:#888; }
    .btn-secondary:hover { background:#666; }
    .status-ok { color: #2e7d32; font-weight: bold; }
    .nav a { margin-right: 1rem; }
    pre { background:#111; color:#ddd; padding:1rem; border-radius:6px; overflow:auto; max-height:60vh; font-size:0.85rem;}
    label { display:block; margin-bottom:0.3rem; font-weight:bold;}
    .row { display:flex; gap:1rem; align-items:center; flex-wrap:wrap; margin-bottom:0.5rem;}
    .muted { color:#777; font-size:0.85rem;}
  </style>
</head>
<body>
  <h1>Heinäautomaatti</h1>
  <p class="muted">Nykyinen aika: {{ now }}</p>
  <div class="nav">
    <a href="{{ url_for('index') }}">Etusivu</a>
    <a href="{{ url_for('log_view') }}">Loki</a>
  </div>

  {% if message %}
    <div class="card status-ok">{{ message }}</div>
  {% endif %}

  <div class="card">
    <h2>Ajastukset</h2>
    <form method="post" action="{{ url_for('save_settings') }}">
      <table>
        <tr>
          <th>Hylly</th>
          <th>GPIO-pinni</th>
          <th>Avautumisaika</th>
          <th>Käytössä</th>
          <th>Testaa</th>
        </tr>
        {% for key, shelf in visible_shelves.items() %}
        <tr>
          <td>{{ shelf.name }}</td>
          <td>{{ shelf.pin }}</td>
          <td><input type="time" name="time_{{ key }}" value="{{ shelf.time }}"></td>
          <td><input type="checkbox" name="enabled_{{ key }}" {% if shelf.enabled %}checked{% endif %}></td>
          <td>
            <button class="btn btn-secondary" type="submit" name="manual" value="{{ key }}"
                    formaction="{{ url_for('manual_trigger', shelf_key=key) }}"
                    onclick="return confirm('Käynnistetään {{ shelf.name }} -sekvenssi heti. Jatka?');">
              Avaa nyt
            </button>
          </td>
        </tr>
        {% endfor %}
      </table>

      <h3>Yleisasetukset</h3>
      <div class="row">
        <div>
          <label>Hyllyn lukon aukipitoaika (s)</label>
          <input type="number" min="1" max="10" name="relay_active_seconds" value="{{ relay_active_seconds }}">
        </div>
        <div>
          <label>Piippausten määrä ennen hyllyn aukaisua</label>
          <input type="number" min="0" max="10" name="beep_count" value="{{ beep_count }}">
        </div>
        <div>
          <label>Yhden piippauksen pituus (s)</label>
          <input type="number" min="1" max="5" name="beep_on_seconds" value="{{ beep_on_seconds }}">
        </div>
        <div>
          <label>Tauko piippausten välissä (s)</label>
          <input type="number" min="1" max="5" name="beep_off_seconds" value="{{ beep_off_seconds }}">
        </div>
      </div>
      <p class="muted">
        Piippaukset alkavat automaattisesti (piippauksia x (piippaus+tauko)) sekuntia
        ennen hyllyn avautumisaikaa. Oletuksilla 5 x (1s+1s) = 10s.
      </p>
      <p class="muted">
        Pidä hyllyn lukon aukipitoaika lyhyenä (max. 2-3 sekuntia), ettei lukon
        magneettisolenoidi kuumene liikaa ja sulata muovia, jossa avaustappi liikkuu.
      </p>

      <button class="btn" type="submit" name="save" value="1">Tallenna asetukset</button>
    </form>
  </div>

  <div class="card">
    <h2>Palvelun hallinta</h2>
    <p class="muted">
      Käynnistä palvelu uudelleen, jos asetusmuutokset eivät ole tulleet voimaan
      tai ajastin ei käynnisty odotetusti. Uudelleenkäynnistys kestää noin 5 sekuntia,
      jonka jälkeen sivu latautuu automaattisesti uudelleen.
    </p>
    <form method="post" action="{{ url_for('restart_service') }}"
          onsubmit="return confirm('Käynnistetäänkö heinäautomaatti-palvelu uudelleen?');">
      <button class="btn btn-danger" type="submit">&#x21BA; Käynnistä palvelu uudelleen</button>
    </form>
  </div>

  <div class="card">
    <h2>Hyllyjen tila</h2>
    <p class="muted">Hyllyjen lukkojen tilavalvontaa ei ole - tässä näkyy vain viimeisin ajastettu aukaisupäivä.</p>
    <ul>
      {% for key, shelf in visible_shelves.items() %}
        <li>{{ shelf.name }}: {{ last_run.get(key, "ei auennut tänään") }}</li>
      {% endfor %}
    </ul>
  </div>

</body>
</html>
"""

LOG_TEMPLATE = """
<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Heinäautomaatti - loki</title>
  <style>
    body { font-family: sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; background:#f7f7f5; color:#222;}
    pre { background:#111; color:#ddd; padding:1rem; border-radius:6px; overflow:auto; max-height:70vh; font-size:0.85rem; white-space: pre-wrap;}
    .btn { background:#3a6b35; color:white; border:none; padding:0.5rem 1rem; border-radius:5px; cursor:pointer; font-size:0.95rem;}
    .btn-danger { background:#a13b3b; }
    .btn-danger:hover { background:#822f2f; }
    .nav a { margin-right: 1rem; }
  </style>
</head>
<body>
  <h1>Tapahtumaloki</h1>
  <div class="nav">
    <a href="{{ url_for('index') }}">Etusivu</a>
    <a href="{{ url_for('log_view') }}">Päivitä</a>
  </div>
  <form method="post" action="{{ url_for('log_clear') }}"
        onsubmit="return confirm('Haluatko varmasti tyhjentää lokin? Tätä ei voi perua.');">
    <button class="btn btn-danger" type="submit">Tyhjennä loki</button>
  </form>
  <pre>{{ log_content }}</pre>
</body>
</html>
"""


def get_visible_shelves(cfg: dict) -> dict:
    """Palauttaa vain hyllyt, joilla visible=true (tai kenttä puuttuu -> näkyvä)."""
    return {
        key: shelf
        for key, shelf in cfg["shelves"].items()
        if shelf.get("visible", True)
    }


@app.route("/", methods=["GET"])
def index():
    cfg = get_config()
    return render_template_string(
        PAGE_TEMPLATE,
        visible_shelves=get_visible_shelves(cfg),
        relay_active_seconds=cfg.get("relay_active_seconds", 2),
        beep_count=cfg.get("beep_count", 5),
        beep_on_seconds=cfg.get("beep_on_seconds", 1),
        beep_off_seconds=cfg.get("beep_off_seconds", 1),
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_run=_last_run_date,
        message=request.args.get("message"),
    )


@app.route("/save", methods=["POST"])
def save_settings():
    cfg = get_config()

    # Päivitetään vain näkyvien hyllyjen tiedot lomakkeelta;
    # piilotettujen hyllyjen asetukset säilyvät config.json:ssa muuttumattomina.
    visible = get_visible_shelves(cfg)
    for key in visible:
        time_value = request.form.get(f"time_{key}")
        if time_value and parse_hhmm(time_value) is not None:
            cfg["shelves"][key]["time"] = time_value
        cfg["shelves"][key]["enabled"] = f"enabled_{key}" in request.form

    def _int(name, default, lo, hi):
        try:
            v = int(request.form.get(name, default))
            return max(lo, min(hi, v))
        except (ValueError, TypeError):
            return default

    cfg["relay_active_seconds"] = _int("relay_active_seconds", cfg.get("relay_active_seconds", 2), 1, 10)
    cfg["beep_count"] = _int("beep_count", cfg.get("beep_count", 5), 0, 10)
    cfg["beep_on_seconds"] = _int("beep_on_seconds", cfg.get("beep_on_seconds", 1), 1, 5)
    cfg["beep_off_seconds"] = _int("beep_off_seconds", cfg.get("beep_off_seconds", 1), 1, 5)

    set_config(cfg)
    log_event("Asetukset tallennettu web-käyttöliittymästä.")
    return redirect(url_for("index", message="Asetukset tallennettu."))


@app.route("/manual/<shelf_key>", methods=["POST"])
def manual_trigger(shelf_key):
    cfg = get_config()
    if shelf_key not in cfg["shelves"]:
        return redirect(url_for("index", message="Tuntematon hylly."))

    shelf = cfg["shelves"][shelf_key]
    # Manuaalinen laukaisu sallitaan vain näkyville hyllyille
    if not shelf.get("visible", True):
        return redirect(url_for("index", message="Hylly ei ole näkyvissä hallintasivulla."))
    if not shelf.get("enabled", True):
        return redirect(url_for("index", message=f"{shelf['name']} ei ole käytössä."))

    trigger_shelf_async(shelf_key, manual=True)
    return redirect(url_for("index", message=f"{shelf['name']}: sekvenssi käynnistetty manuaalisesti."))


@app.route("/log", methods=["GET"])
def log_view():
    return render_template_string(LOG_TEMPLATE, log_content=read_log() or "(loki on tyhjä)")


@app.route("/log/clear", methods=["POST"])
def log_clear():
    clear_log()
    return redirect(url_for("log_view"))


def _do_restart():
    """Ajaa systemctl restart pienellä viiveellä taustasäikeessä,
    jotta Flask ehtii lähettää välisivun selaimelle ennen katkoa."""
    time.sleep(2)
    log_event("Palvelun uudelleenkäynnistys käynnistyy.")
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "heina-automaatti.service"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            log_event("Palvelu käynnistetty uudelleen onnistuneesti.")
        else:
            log_event(
                f"Uudelleenkäynnistys epäonnistui (koodi {result.returncode}): "
                f"{result.stderr.strip()}"
            )
    except subprocess.TimeoutExpired:
        log_event("Uudelleenkäynnistys aikakatkaistiin (timeout 15s).")
    except Exception as exc:
        log_event(f"Uudelleenkäynnistysvirhe: {exc}")


@app.route("/restart", methods=["POST"])
def restart_service():
    """Käynnistää heina-automaatti.service -palvelun uudelleen systemd:n kautta.

    Edellyttää, että /etc/sudoers.d/heina-automaatti sisältää rivin:
      pi ALL=(ALL) NOPASSWD: /bin/systemctl restart heina-automaatti.service
    """
    log_event("Palvelun uudelleenkäynnistys pyydetty web-käyttöliittymästä.")

    # Käynnistä restart taustasäikeessä — näin Flask ehtii palauttaa
    # välisivun selaimelle ennen kuin prosessi katkeaa.
    t = threading.Thread(target=_do_restart, daemon=True)
    t.start()

    # Välisivu: JavaScript yrittää toistuvasti ladata etusivua kunnes palvelu
    # on taas ylhäällä. meta refresh varmuuden vuoksi.
    return """
<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="10; url=/">
  <title>Käynnistetään uudelleen...</title>
  <style>
    body { font-family: sans-serif; max-width: 500px; margin: 4rem auto;
           padding: 0 1rem; background:#f7f7f5; color:#222; text-align:center; }
    .spinner { font-size: 2rem; animation: spin 1s linear infinite; display:inline-block; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="spinner">&#x21BB;</div>
  <h2>Palvelu käynnistyy uudelleen&hellip;</h2>
  <p>Sinut ohjataan etusivulle automaattisesti kun palvelu on taas ylhäällä.</p>
  <p><a href="/">Siirry etusivulle</a></p>
  <script>
    // Yritetään etusivua 2 sekunnin välein; siirrytään sinne kun se vastaa.
    var attempts = 0;
    var timer = setInterval(function() {
      attempts++;
      fetch("/", { method: "HEAD" })
        .then(function(r) {
          if (r.ok) { clearInterval(timer); window.location.href = "/"; }
        })
        .catch(function() { /* palvelu ei vielä ylhäällä, odotetaan */ });
      if (attempts > 30) clearInterval(timer); // luovutetaan 60s jälkeen
    }, 2000);
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Pääohjelma
# ---------------------------------------------------------------------------

def main():
    global _config

    _config = load_config()
    log_event("Heinäautomaatti käynnistyy.")

    # Logataan käynnistyksen yhteydessä hyllyjen tila
    for key, shelf in _config["shelves"].items():
        status = "näkyvissä" if shelf.get("visible", True) else "piilotettu"
        aktiivinen = "käytössä" if shelf.get("enabled", True) else "ei käytössä"
        log_event(f"  Hylly '{shelf['name']}' (pinni {shelf['pin']}): {aktiivinen}, {status} UI:ssa.")

    gpio_setup()

    stop_event = threading.Event()
    scheduler_thread = threading.Thread(target=scheduler_loop, args=(stop_event,), daemon=True)
    scheduler_thread.start()

    try:
        serve(app, host=WEB_HOST, port=WEB_PORT)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        scheduler_thread.join(timeout=2)
        gpio_cleanup()
        log_event("Heinäautomaatti pysäytetty.")


if __name__ == "__main__":
    main()
