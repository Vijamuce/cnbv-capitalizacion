#!/usr/bin/env python3
"""Revisa semanalmente si la CNBV publicó cifras nuevas de capitalización
para bancos, SOFIPOS, SOCAPs y casas de bolsa, y actualiza los JSON en
docs/data/. Fintech se revisa aparte (no tiene un boletín recurrente).

Diseñado para correr en GitHub Actions (ubuntu-latest, con poppler-utils
instalado). Cada función de sector es independiente: si una falla o no
encuentra nada nuevo, no bloquea a las demás.
"""
import json
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def log(msg):
    print(msg, flush=True)


def next_months(iso_date, count=3):
    """Da los próximos `count` (año, mes) después de la fecha 'cifras al' actual."""
    y, m, _ = [int(x) for x in iso_date.split("-")]
    out = []
    for _ in range(count):
        m += 1
        if m > 12:
            m = 1
            y += 1
        out.append((y, m))
    return out


def fetch_url(url, insecure=False, timeout=25):
    """Descarga bytes de una URL. insecure=True para portafolioinfo.cnbv.gob.mx
    (certificado con cadena incompleta, dominio público de gob.mx)."""
    import ssl
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.status, resp.read()


def pdf_to_text(pdf_bytes, tmp_path):
    tmp_path.write_bytes(pdf_bytes)
    txt_path = tmp_path.with_suffix(".txt")
    subprocess.run(["pdftotext", "-layout", str(tmp_path), str(txt_path)], check=True)
    return txt_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# BANCOS
# ---------------------------------------------------------------------------

def check_bancos():
    path = DATA_DIR / "bancos.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    for y, m in next_months(data["cifras"]):
        mes_nombre = MESES[m - 1]
        page_url = (f"https://www.gob.mx/cnbv/prensa/indice-de-capitalizacion-de-la-banca-multiple-"
                    f"al-cierre-de-{mes_nombre}-de-{y}?idiom=es")
        try:
            status, html = fetch_url(page_url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log(f"[bancos] {mes_nombre} {y}: sin boletín todavía (404)")
                continue
            raise
        except Exception as e:
            log(f"[bancos] {mes_nombre} {y}: error de red, me detengo aquí: {e}")
            return False

        html_text = html.decode("utf-8", errors="ignore")
        m_pdf = re.search(r'https://www\.gob\.mx/cms/uploads/attachment/file/\d+/Comunicado[^"\')\s]+\.pdf', html_text)
        if not m_pdf:
            log(f"[bancos] {mes_nombre} {y}: página existe pero no encontré el PDF adjunto, reviso a mano")
            return False
        pdf_url = m_pdf.group(0)
        log(f"[bancos] Encontrado boletín nuevo: {pdf_url}")

        status, pdf_bytes = fetch_url(pdf_url)
        text = pdf_to_text(pdf_bytes, Path("/tmp/comunicado_bancos.pdf"))

        cifras_match = re.search(r'CIFRAS AL (\d{1,2}) DE (\w+) DE (\d{4})', text.upper())
        if not cifras_match:
            log("[bancos] no encontré la línea 'CIFRAS AL', abortando este sector")
            return False
        d, mes_txt, year_txt = cifras_match.groups()
        mes_idx = MESES.index(mes_txt.lower()) + 1 if mes_txt.lower() in MESES else None
        cifras_iso = f"{year_txt}-{mes_idx:02d}-{int(d):02d}" if mes_idx else data["cifras"]

        row_re = re.compile(
            r'^([A-ZÁÉÍÓÚÑa-záéíóúñ0-9.,\'&\- ]+?)\s+(-?\d[\d,]*\.\d{2})\s+(-?\d[\d,]*\.\d{2})\s+(-?\d[\d,]*\.\d{2})\s+(I{1,3}V?|IV|V)\s*$'
        )
        rows = []
        total_index = None
        for line in text.splitlines():
            line = line.strip()
            mm = row_re.match(line)
            if not mm:
                continue
            name, ccb, ccf, icap, cat = mm.groups()
            name = name.strip()
            if name.lower().startswith("total"):
                total_index = float(icap.replace(",", ""))
                continue
            rows.append({
                "name": name,
                "ccb": float(ccb.replace(",", "")),
                "ccf": float(ccf.replace(",", "")),
                "icap": float(icap.replace(",", "")),
                "cat": cat,
            })

        if len(rows) < 40:
            log(f"[bancos] solo parseé {len(rows)} filas (se esperan ~50+), algo salió mal, no publico y reviso a mano")
            return False

        total_match = re.search(r'Total Banca M[uú]ltiple\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})', text)
        if total_match:
            total_index = float(total_match.group(3).replace(",", ""))

        comunicado_match = re.search(r'Comunicado No\.?:?\s*(\d+)', text)
        pub_match = re.search(r'Ciudad de M[eé]xico,\s*(\d{1,2} de \w+ de \d{4})', text)
        publicado = f"{pub_match.group(1)}" if pub_match else data["publicado"]
        if comunicado_match:
            publicado += f" · Comunicado {comunicado_match.group(1)}"

        data["cifras"] = cifras_iso
        data["publicado"] = publicado
        data["source_url"] = page_url
        data["index"] = total_index if total_index is not None else data["index"]
        data["rows"] = rows
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[bancos] actualizado: {len(rows)} instituciones, cifras al {cifras_iso}")
        return True

    log("[bancos] sin novedades")
    return False


# ---------------------------------------------------------------------------
# SOFIPOS y SOCAPs (portafolioinfo.cnbv.gob.mx)
# ---------------------------------------------------------------------------

ROW_RE_SOFIPOS = re.compile(
    r'^\s*(\d+)\s+(\d{6})\s+(.+?)\s+(-|-?[\d,]+|[nN]\.[dD]\.?)\s+(-|-?[\d,]+|[nN]\.[dD]\.?)\s+'
    r'(-?[\d.,]+%|[nN]\.[dD]\.?)\s+(\d|[nN]\.[dD]\.?)\s+(\S.*\S|\S)\s*$'
)
ROW_RE_SOCAPS = re.compile(
    r'^\s*(\d{5})\s+(.+?)\s+(-?[\d,]+|N\.D\.?)\s+(-?[\d,]+|N\.D\.?)\s+(-?[\d.,]+%|N\.D\.?)\s+(\d|N\.D\.?|N\.A\.?)\s*$'
)


def _num(s):
    if s is None:
        return None
    s = s.strip()
    if s.lower() in ("-", "n.d.", "n.d", "n.a.", "n.a"):
        return None
    return int(s.replace(",", ""))


def _pct(s):
    if s is None:
        return None
    s = s.strip().rstrip("%")
    if s.lower() in ("n.d.", "n.d", "n.a.", "n.a"):
        return None
    return float(s.replace(",", ""))


def _cat(s):
    s = s.strip()
    if s.lower() in ("n.d.", "n.d"):
        return None
    return s


def check_popular_sector(kind):
    """kind = 'sofipos' o 'socaps'"""
    fname = "ICAP_SOFIPOS" if kind == "sofipos" else "NICAP_SOCAPS"
    path = DATA_DIR / f"{kind}.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    for y, m in next_months(data["cifras"]):
        url = f"https://portafolioinfo.cnbv.gob.mx/PortafolioInformacion/{fname}_{y}{m:02d}.pdf"
        try:
            status, pdf_bytes = fetch_url(url, insecure=True)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log(f"[{kind}] {y}-{m:02d}: sin boletín todavía (404)")
                continue
            raise
        except Exception as e:
            log(f"[{kind}] {y}-{m:02d}: error de red, me detengo aquí: {e}")
            return False

        log(f"[{kind}] Encontrado PDF: {url}")
        text = pdf_to_text(pdf_bytes, Path(f"/tmp/{kind}.pdf"))

        cifras_match = re.search(r'CIFRAS AL (\d{1,2}) DE (\w+) DE (\d{4})', text.upper())
        if not cifras_match:
            log(f"[{kind}] no encontré 'CIFRAS AL' en el PDF, abortando este sector")
            return False
        d, mes_txt, year_txt = cifras_match.groups()
        mes_idx = None
        for i, mn in enumerate(MESES):
            if mn.upper() == mes_txt.upper():
                mes_idx = i + 1
        if not mes_idx:
            log(f"[{kind}] no reconocí el mes '{mes_txt}', abortando")
            return False
        cifras_iso = f"{year_txt}-{mes_idx:02d}-{int(d):02d}"

        rows = []
        total_index = None
        stop_marker = "Total SOFIPOS" if kind == "sofipos" else "Total SOCAP"
        for line in text.splitlines():
            if stop_marker in line:
                nums = re.findall(r'[\d,]+\.\d{2}%', line)
                if nums:
                    total_index = float(nums[-1].rstrip("%").replace(",", ""))
                break
            raw = line.rstrip("\n")
            if kind == "sofipos":
                mm = ROW_RE_SOFIPOS.match(raw)
                if not mm:
                    continue
                _, _, name, capital, req, nicap, cat, fed = mm.groups()
                name = re.sub(r"\s*\d+/\s*$", "", name).strip()
                rows.append({"name": name, "capital": _num(capital), "req": _num(req),
                             "nicap": _pct(nicap), "cat": _cat(cat), "fed": fed.strip()})
            else:
                mm = ROW_RE_SOCAPS.match(raw)
                if not mm:
                    continue
                clave, name, capital, req, nicap, cat = mm.groups()
                name = re.sub(r"\s*/\d+\s*$", "", name).strip()
                rows.append({"name": name, "capital": _num(capital), "req": _num(req),
                             "nicap": _pct(nicap), "cat": _cat(cat)})

        expected_min = 20 if kind == "sofipos" else 100
        if len(rows) < expected_min:
            log(f"[{kind}] solo parseé {len(rows)} filas (se esperan {expected_min}+), no publico, reviso a mano")
            return False

        data["cifras"] = cifras_iso
        data["publicado"] = f"Corte {date.today().strftime('%d %b %Y')}"
        data["source_url"] = url
        if total_index is not None:
            data["index"] = total_index
        data["rows"] = rows
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[{kind}] actualizado: {len(rows)} instituciones, cifras al {cifras_iso}")
        return True

    log(f"[{kind}] sin novedades")
    return False


# ---------------------------------------------------------------------------
# CASAS DE BOLSA (solo agregado del sistema, no hay tabla por institución)
# ---------------------------------------------------------------------------

def check_casas_de_bolsa():
    path = DATA_DIR / "casas_de_bolsa.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    for y, m in next_months(data["cifras"]):
        mes_nombre = MESES[m - 1]
        page_url = (f"https://www.gob.mx/cnbv/prensa/indice-de-capitalizacion-de-casas-de-bolsa-"
                    f"al-cierre-de-{mes_nombre}-de-{y}?idiom=es")
        try:
            status, html = fetch_url(page_url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log(f"[casas_de_bolsa] {mes_nombre} {y}: sin boletín todavía (404)")
                continue
            raise
        except Exception as e:
            log(f"[casas_de_bolsa] {mes_nombre} {y}: error de red, me detengo aquí: {e}")
            return False

        html_text = html.decode("utf-8", errors="ignore")
        pct_match = re.search(r'ubic[oó]\s+en\s+(\d+\.\d+)\s*%', html_text)
        if not pct_match:
            log("[casas_de_bolsa] página existe pero no encontré el % agregado, reviso a mano")
            return False

        data["cifras"] = f"{y}-{m:02d}-{28 if m == 2 else 30}"
        data["publicado"] = f"Publicado {date.today().strftime('%d %b %Y')}"
        data["source_url"] = page_url
        data["index"] = float(pct_match.group(1))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[casas_de_bolsa] actualizado: ICAP {data['index']}%")
        return True

    log("[casas_de_bolsa] sin novedades")
    return False


# ---------------------------------------------------------------------------
# FINTECH (sin boletín recurrente: solo marcamos la revisión semanal)
# ---------------------------------------------------------------------------

def check_fintech():
    path = DATA_DIR / "fintech.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        status, html = fetch_url("https://www.gob.mx/cnbv/acciones-y-programas/instituciones-de-tecnologia-financiera-fintech")
        html_text = html.decode("utf-8", errors="ignore")
        if "capitaliz" in html_text.lower() or "ICAP" in html_text:
            log("[fintech] posible mención de capitalización en la página del programa fintech — revisar a mano")
    except Exception as e:
        log(f"[fintech] no pude revisar la página del programa: {e}")

    data["last_checked"] = date.today().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log("[fintech] revisión semanal registrada (sin boletín recurrente conocido)")
    return False


def main():
    changed = False
    for fn, name in [(check_bancos, "bancos"), (lambda: check_popular_sector("sofipos"), "sofipos"),
                      (lambda: check_popular_sector("socaps"), "socaps"),
                      (check_casas_de_bolsa, "casas_de_bolsa"), (check_fintech, "fintech")]:
        try:
            if fn():
                changed = True
        except Exception as e:
            log(f"[{name}] ERROR inesperado, sigo con el resto: {e}")
    if changed:
        log("Hubo actualizaciones.")
    else:
        log("Sin actualizaciones esta semana.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
