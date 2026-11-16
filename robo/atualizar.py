# Robo gratuito: baixa dados oficiais (CVM e B3) e gera data/mercado.json
import io, csv, json, zipfile, datetime as dt, requests

HOJE = dt.date.today()
ST = {}

def baixar(url):
    r = requests.get(url, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.content

def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None

def col(row, *nomes):
    for k in row:
        kl = k.lower()
        if all(n in kl for n in nomes):
            return row[k]
    return None

def cvm(ano):
    z = zipfile.ZipFile(io.BytesIO(baixar(
        "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_%d.zip" % ano)))
    out = {}
    for n in z.namelist():
        k = "geral" if "_geral_" in n else "compl" if "_complemento_" in n else None
        if k:
            out[k] = list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="latin-1"), delimiter=";"))
    return out

def cotacoes(ano):
    z = zipfile.ZipFile(io.BytesIO(baixar(
        "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A%d.ZIP" % ano)))
    D = {}
    for l in io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1"):
        if l[:2] != "01" or l[24:27] != "010":
            continue
        t = l[12:24].strip()
        if len(t) == 6 and t.endswith("11"):
            D.setdefault(t, []).append((l[2:10], int(l[108:121]) / 100, int(l[170:188]) / 100))
    return D

def main():
    # 1) Cotacoes e liquidez (B3)
    try:
        C = cotacoes(HOJE.year)
        ST["b3"] = "ok: %d codigos" % len(C)
    except Exception as e:
        C = {}
        ST["b3"] = "erro: %s" % e
    # 2) Informe mensal (CVM): este ano e o anterior
    tick, hist = {}, {}
    for ano in (HOJE.year - 1, HOJE.year):
        try:
            d = cvm(ano)
            for r in d.get("geral", []):
                cnpj, isin = col(r, "cnpj"), (col(r, "isin") or "")
                if cnpj and isin.startswith("BR") and "CTF" in isin:
                    tick[cnpj] = isin[2:6] + "11"
            for r in d.get("compl", []):
                cnpj, ref = col(r, "cnpj"), col(r, "data_ref")
                ver = int(col(r, "versao") or 0)
                a = hist.setdefault(cnpj, {})
                if ref not in a or ver >= a[ref][0]:
                    a[ref] = (ver, num(col(r, "valor_patrimonial")), num(col(r, "dividend_yield")))
            if d.get("compl"):
                ST["colunas"] = list(d["compl"][0].keys())
            ST["cvm%d" % ano] = "ok"
        except Exception as e:
            ST["cvm%d" % ano] = "erro: %s" % e
    # 3) Indicadores por fundo (usa o CNPJ com informe mais recente de cada codigo)
    vals = sorted(v[2] for m in hist.values() for v in m.values() if v[2])
    esc = 100 if vals and vals[len(vals) // 2] < 0.05 else 1
    ST["dy_escala"] = esc
    ST["dy_mes_mediana"] = vals[len(vals) // 2] if vals else None
    por_t = {}
    for cnpj, meses in hist.items():
        t = tick.get(cnpj)
        if t:
            por_t.setdefault(t, []).append((max(meses), cnpj))
    F, defas, diag = {}, [], {}
    for t, lst in por_t.items():
        ref, cnpj = max(lst)
        meses = hist[cnpj]
        if t not in C:
            continue
        refs = sorted(meses)[-12:]
        vp = meses[refs[-1]][1]
        dys = [meses[r][2] for r in refs if meses[r][2]]
        sess = sorted(C[t])[-20:]
        preco = sess[-1][1]
        try:
            idade = (HOJE - dt.date.fromisoformat(ref[:10])).days
        except Exception:
            idade = 999
        motivo = None
        if idade > 120:
            defas.append(t)
            motivo = "dados da CVM defasados (ultimo informe %s)" % ref[:10]
        elif not vp or preco <= 0 or len(sess) < 10:
            motivo = "sem VP ou poucas negociacoes"
        if motivo is None:
            dy = None
            if len(dys) >= 6:
                dy = sum(dys) * esc * 12 / len(dys) / 100 * vp / preco * 100
                dy = round(dy, 1) if 0 < dy < 40 else None
            pvp = preco / vp
            if 0.2 < pvp < 3:
                F[t] = {"preco": round(preco, 2), "pvp": round(pvp, 2), "dy": dy,
                        "liq": round(sum(s[2] for s in sess) / len(sess) / 1000), "ref": refs[-1]}
        if t in ("AAZQ11", "AGRX11", "CPTR11", "FGAA11"):
            diag[t] = ("ok " + json.dumps(F[t])) if t in F else (motivo or "fora da faixa de P/VP")
    for t in ("AAZQ11", "AGRX11", "CPTR11", "FGAA11"):
        if t not in diag:
            diag[t] = "sem cotacao na B3" if t not in C else "sem historico na CVM"
    ST["diag"] = diag
    ST["n_defasados"] = len(defas)
    ST["defasados"] = sorted(defas)[:40]
    ST["fundos"] = len(F)
    ST["com_dy"] = len([1 for f in F.values() if f["dy"] is not None])
    if F:  # so sobrescreve se deu certo
        json.dump({"atualizado": HOJE.isoformat(), "status": ST, "fundos": F},
                  open("data/mercado.json", "w"), ensure_ascii=False, indent=1)
    print(ST)

main()
