# Robo gratuito: baixa dados oficiais (CVM e B3) e gera data/mercado.json
import io, re, csv, json, zipfile, datetime as dt, requests

HOJE = dt.date.today()
ISIN2T = {}
MEUS = ["AAZQ11","AGRX11","CPTR11","FGAA11","GARE11","GGRC11","LIFE11","MANA11","MCRE11","RURA11","RZAG11","SNEL11","VGIA11","WHGR11","XPCA11"]
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

def fiagro():
    """Informes mensais de Fiagro (conjunto separado da CVM, ultimos 12 meses)."""
    a, m = HOJE.year, HOJE.month
    tk, hs, arqs, nlin = {}, {}, {}, 0
    for _ in range(13):
        m -= 1
        if m == 0:
            a, m = a - 1, 12
        ym = "%d%02d" % (a, m)
        try:
            z = zipfile.ZipFile(io.BytesIO(baixar(
                "https://dados.cvm.gov.br/dados/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_%s.zip" % ym)))
        except Exception:
            continue
        for n in z.namelist():
            if not n.lower().endswith(".csv"):
                continue
            rows = list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="latin-1"), delimiter=";"))
            if rows:
                arqs.setdefault(n.replace(ym, "AAAAMM"), list(rows[0].keys())[:60])
            for r in rows:
                nlin += 1
                cnpj = col(r, "cnpj")
                ref = col(r, "data_ref") or col(r, "competencia") or col(r, "dt_comptc")
                if not cnpj or not ref:
                    continue
                isin = (col(r, "isin") or "").strip()
                if isin.startswith("BR") and "CTF" in isin:
                    tk[cnpj] = isin[2:6] + "11"
                if isin in ISIN2T:
                    tk[cnpj] = ISIN2T[isin]
                for k, v in r.items():
                    if v and re.fullmatch(r"[A-Z]{4}11", v.strip()) and any(x in k.lower() for x in ("negoc", "ticker", "codigo")):
                        tk[cnpj] = v.strip()
                vp, dy = num(col(r, "valor_patrimonial")), num(col(r, "dividend_yield"))
                p = hs.setdefault(cnpj, {}).get(ref, (0, None, None))
                hs[cnpj][ref] = (0, vp or p[1], dy or p[2])
    # normaliza a escala do DY dos Fiagros para fracao (0,0085 = 0,85%)
    vs = sorted(v[2] for mm in hs.values() for v in mm.values() if v[2])
    med = vs[len(vs) // 2] if vs else None
    if med is not None and med >= 0.05:
        for c in hs:
            hs[c] = {r: (v[0], v[1], (v[2] / 100 if v[2] else v[2])) for r, v in hs[c].items()}
    ST["fiagro_dy_mediana_original"] = med
    ST["fiagro"] = {"arquivos": arqs, "linhas": nlin, "cnpjs": len(hs), "com_ticker": len([c for c in hs if c in tk])}
    return tk, hs

BASE = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_%s.ZIP"

def ler_cotahist(conteudo, D):
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    for l in io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1"):
        if l[:2] != "01" or l[24:27] != "010":
            continue
        t = l[12:24].strip()
        if len(t) == 6 and t.endswith("11"):
            ISIN2T[l[230:242].strip()] = t
            D.setdefault(t, {})[l[2:10]] = (int(l[108:121]) / 100, int(l[170:188]) / 100)

def cotacoes():
    """Tenta o arquivo anual; se nao existir, usa mensais (meses fechados) + diarios do mes corrente."""
    D, erros, usados = {}, [], []
    def tentar(nome):
        try:
            ler_cotahist(baixar(BASE % nome), D)
            usados.append(nome)
            return True
        except Exception as e:
            erros.append("%s: %s" % (nome, str(e)[:70]))
            return False
    if not tentar("A%d" % HOJE.year):
        ref = HOJE.replace(day=1)
        for _ in range(2):  # dois meses fechados
            ref = ref - dt.timedelta(days=1)
            tentar("M%02d%d" % (ref.month, ref.year))
            ref = ref.replace(day=1)
        dia = HOJE.replace(day=1)
        while dia <= HOJE:  # dias uteis do mes corrente
            if dia.weekday() < 5:
                tentar("D%02d%02d%d" % (dia.day, dia.month, dia.year))
            dia += dt.timedelta(days=1)
        if not D:  # ultima tentativa: ultimos 45 dias
            for k in range(1, 46):
                dia = HOJE - dt.timedelta(days=k)
                if dia.weekday() < 5:
                    tentar("D%02d%02d%d" % (dia.day, dia.month, dia.year))
    ST["b3_arquivos"] = "%d ok" % len(usados) + (" (ex.: %s)" % usados[-1] if usados else "")
    if erros:
        ST["b3_erros"] = erros[:4]
    return {t: sorted((d, p, v) for d, (p, v) in dd.items()) for t, dd in D.items()}

def main():
    # 1) Cotacoes e liquidez (B3)
    try:
        C = cotacoes()
        ST["b3"] = ("ok: %d codigos" % len(C)) if C else "erro: nenhum arquivo de cotacoes baixado"
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
                if isin in ISIN2T:
                    tick[cnpj] = ISIN2T[isin]
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
    agro = set()
    # 2b) Fiagros (conjunto proprio da CVM)
    try:
        tk2, hs2 = fiagro()
        tick.update(tk2)
        agro = set(tk2)
        for c, mm in hs2.items():
            hist.setdefault(c, {}).update(mm)
    except Exception as e:
        ST["fiagro_erro"] = str(e)
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
                F[t] = {"tp": "Agro" if cnpj in agro else "FII", "preco": round(preco, 2), "pvp": round(pvp, 2), "dy": dy,
                        "liq": round(sum(s[2] for s in sess) / len(sess) / 1000), "ref": refs[-1]}
        if t in MEUS:
            diag[t] = ("ok " if t in F else (motivo or "fora da faixa de P/VP")) + " | ref=" + ref[:10] + " vp=" + str(vp) + " dy_mensal=" + str([round(d * esc, 3) for d in dys]) + (" | " + json.dumps(F[t]) if t in F else "")
    for t in MEUS:
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
