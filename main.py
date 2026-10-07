"""
Candidatura Fácil V4 — Versão para Render
Scraping real de vagasmoz.com + personalização de CV e carta
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import httpx
import feedparser
import re
import json
import os
from datetime import datetime
from pathlib import Path

# ---------------------- Config ----------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

PERFIL_FILE = DATA_DIR / "perfil.json"
CANDIDATURAS_FILE = DATA_DIR / "candidaturas.json"
VAGAS_CACHE_FILE = DATA_DIR / "vagas_cache.json"

RSS_URL = "https://vagasmoz.com/?feed=job_feed"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

app = FastAPI(title="Candidatura Fácil V4", version="4.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------- Models ----------------------
class Perfil(BaseModel):
    nome: str = ""
    cargo: str = ""
    email: str = ""
    telefone: str = ""
    local: str = "Maputo"
    salario_min: int = 0
    experiencia: int = 0
    min_score: int = 30
    skills: str = ""
    formacao: str = ""
    resumo: str = ""
    experiencia_texto: str = ""
    auto: bool = False


class CandidaturaCreate(BaseModel):
    vaga_id: str
    titulo: str
    empresa: str
    local: str
    score: int
    url: str
    descricao: str = ""


class CandidaturaUpdate(BaseModel):
    estado: str


# ---------------------- Storage ----------------------
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_perfil() -> dict:
    return load_json(PERFIL_FILE, Perfil().model_dump())


def save_perfil(perfil: dict):
    save_json(PERFIL_FILE, perfil)


def get_candidaturas() -> list:
    return load_json(CANDIDATURAS_FILE, [])


def save_candidaturas(cands: list):
    save_json(CANDIDATURAS_FILE, cands)


# ---------------------- Helpers ----------------------
def limpar_texto(texto: str) -> str:
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def extrair_empresa_local(titulo: str, descricao: str) -> tuple:
    empresa = ""
    local = ""
    desc_limpa = limpar_texto(descricao)[:400]

    locs = ["Maputo", "Matola", "Beira", "Nampula", "Pemba", "Quelimane",
            "Tete", "Chimoio", "Xai-Xai", "Inhambane", "Lichinga", "Zambézia",
            "Cabo Delgado", "Niassa", "Gaza", "Manica", "Sofala", "Alto-Molócuè"]
    for loc in locs:
        if loc.lower() in (titulo + " " + desc_limpa).lower():
            local = loc
            break

    match = re.search(r"<strong>([^<]{3,60})</strong>", descricao or "")
    if match:
        empresa = match.group(1).strip()
    else:
        palavras = desc_limpa.split()
        if len(palavras) > 2:
            empresa = " ".join(palavras[:5])

    return empresa or "Não especificada", local or "Moçambique"


def calcular_score(vaga: dict, perfil: dict) -> int:
    score = 25
    titulo = (vaga.get("titulo") or "").lower()
    desc = (vaga.get("descricao") or "").lower()
    local_vaga = (vaga.get("local") or "").lower()
    texto = titulo + " " + desc

    cargo = (perfil.get("cargo") or "").lower()
    skills = [s.strip().lower() for s in (perfil.get("skills") or "").split(";") if s.strip()]
    if not skills:
        skills = [s.strip().lower() for s in (perfil.get("skills") or "").split(",") if s.strip()]
    local_perfil = (perfil.get("local") or "").lower()
    exp = perfil.get("experiencia") or 0

    # Cargo
    for p in [w for w in cargo.split() if len(w) > 3]:
        if p in titulo:
            score += 22
            break
        elif p in texto:
            score += 12
            break

    # Skills
    matches = sum(1 for s in skills if s and len(s) > 2 and s in texto)
    score += min(matches * 9, 28)

    # Local
    if local_perfil and local_vaga:
        if local_perfil in local_vaga or local_vaga in local_perfil:
            score += 15

    # Experiência
    exp_match = re.search(r"(\d+)\s*\+?\s*anos?", texto)
    if exp_match:
        anos_req = int(exp_match.group(1))
        if exp >= anos_req:
            score += 12
        elif exp >= max(0, anos_req - 1):
            score += 6
    else:
        score += 5

    # Área saúde
    area = ["médico", "medicina", "clínico", "saúde", "enfermeiro", "técnico de medicina",
            "generalista", "farmácia", "laboratório", "oficial clínico"]
    for p in area:
        if p in cargo and p in texto:
            score += 10
            break

    return max(10, min(96, round(score)))


# ---------------------- Personalização melhorada ----------------------
def gerar_cv_adaptado(vaga: dict, perfil: dict) -> str:
    nome = perfil.get("nome") or "Candidato"
    cargo = perfil.get("cargo") or "Profissional"
    local = perfil.get("local") or ""
    formacao = perfil.get("formacao") or ""
    skills = perfil.get("skills") or ""
    exp_texto = perfil.get("experiencia_texto") or ""
    resumo = perfil.get("resumo") or ""
    anos = perfil.get("experiencia") or 0
    email = perfil.get("email") or ""
    telefone = perfil.get("telefone") or ""

    titulo_vaga = vaga.get("titulo", "")
    empresa = vaga.get("empresa", "")

    # Resumo adaptado
    if resumo:
        resumo_final = resumo
    else:
        resumo_final = (
            f"Profissional com formação em {formacao or cargo}, "
            f"com {anos} ano(s) de experiência. "
            f"Orientado para resultados e com forte sentido de responsabilidade, "
            f"disponível para integrar a equipa da {empresa} na função de {titulo_vaga}."
        )

    # Competências
    skills_lista = [s.strip() for s in re.split(r"[;,]", skills) if s.strip()]
    skills_fmt = "\n".join(f"• {s}" for s in skills_lista) if skills_lista else "• A preencher"

    cv = f"""CURRICULUM VITAE
(Adaptado à vaga: {titulo_vaga})

DADOS PESSOAIS
Nome: {nome}
Contacto: {telefone} | {email}
Localização: {local}

RESUMO PROFISSIONAL
{resumo_final}

COMPETÊNCIAS
{skills_fmt}

EXPERIÊNCIA PROFISSIONAL
{exp_texto or "• Experiência a detalhar conforme histórico profissional"}

FORMAÇÃO ACADÉMICA
{formacao or "• Formação a indicar"}

---
Documento gerado pelo Candidatura Fácil V4 – personalizado para esta vaga.
"""
    return cv.strip()


def gerar_carta(vaga: dict, perfil: dict) -> str:
    nome = perfil.get("nome") or "Candidato"
    cargo = perfil.get("cargo") or "profissional"
    local = perfil.get("local") or "Moçambique"
    formacao = perfil.get("formacao") or ""
    skills = perfil.get("skills") or ""
    anos = perfil.get("experiencia") or 0
    exp_texto = perfil.get("experiencia_texto") or ""

    titulo_vaga = vaga.get("titulo", "a vaga anunciada")
    empresa = vaga.get("empresa", "a vossa instituição")
    local_vaga = vaga.get("local", "")

    # Extrair algumas competências para mencionar
    skills_lista = [s.strip() for s in re.split(r"[;,]", skills) if s.strip()][:3]
    skills_txt = ", ".join(skills_lista) if skills_lista else "as competências adquiridas ao longo da minha formação e experiência"

    carta = f"""Assunto: Candidatura à vaga de {titulo_vaga}

Exmos. Senhores da {empresa},

Espero que esta mensagem os encontre bem.

Venho por este meio apresentar a minha candidatura à vaga de {titulo_vaga}, recentemente anunciada{f" para {local_vaga}" if local_vaga else ""}.

Sou {nome}, {cargo.lower()} com {anos} ano(s) de experiência profissional e formação em {formacao or "área relevante"}. Ao longo do meu percurso tenho desenvolvido competências em {skills_txt}, que acredito serem úteis para o desempenho das funções descritas.

{f"Destaco a minha experiência como {exp_texto}." if exp_texto else "Tenho procurado desenvolver um trabalho sério, responsável e orientado para o serviço às pessoas."}

Tenho particular interesse em integrar a vossa equipa e contribuir com dedicação, profissionalismo e vontade de aprender. Estou disponível para entrevista em qualquer data e horário que vos seja conveniente.

Agradeço antecipadamente a atenção dispensada à minha candidatura e fico a aguardar o vosso contacto.

Com os melhores cumprimentos,

{nome}
{local}
{perfil.get("telefone") or ""}
{perfil.get("email") or ""}
"""
    return carta.strip()


# ---------------------- Scraping ----------------------
async def buscar_vagas_vagasmoz(perfil: dict) -> list:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Referer": "https://vagasmoz.com/",
    }

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        try:
            resp = await client.get(RSS_URL, headers=headers)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erro ao contactar vagasmoz: {str(e)}")

    feed = feedparser.parse(content)
    vagas = []

    for entry in feed.entries[:40]:
        titulo = limpar_texto(entry.get("title", ""))
        link = entry.get("link", "")
        descricao = entry.get("summary", "") or entry.get("description", "")
        pub = entry.get("published", "")

        empresa, local = extrair_empresa_local(titulo, descricao)

        vaga = {
            "id": entry.get("id", link) or link,
            "titulo": titulo,
            "empresa": empresa,
            "local": local,
            "url": link,
            "descricao": limpar_texto(descricao)[:700],
            "data": pub,
            "fonte": "vagasmoz.com"
        }
        vaga["score"] = calcular_score(vaga, perfil)
        vagas.append(vaga)

    vagas.sort(key=lambda x: x["score"], reverse=True)

    save_json(VAGAS_CACHE_FILE, {
        "atualizado": datetime.now().isoformat(),
        "total": len(vagas),
        "vagas": vagas
    })
    return vagas


# ---------------------- Endpoints ----------------------
@app.get("/api/health")
async def health():
    return {"status": "ok", "versao": "4.2.0", "fonte": "vagasmoz.com"}


@app.get("/api/perfil")
async def obter_perfil():
    return get_perfil()


@app.post("/api/perfil")
async def atualizar_perfil(perfil: Perfil):
    data = perfil.model_dump()
    save_perfil(data)
    return {"ok": True, "perfil": data}


@app.get("/api/vagas")
async def listar_vagas(min_score: Optional[int] = None, forcar: bool = False):
    perfil = get_perfil()
    min_score = min_score if min_score is not None else perfil.get("min_score", 30)

    cache = load_json(VAGAS_CACHE_FILE, {})
    if not forcar and cache.get("vagas"):
        try:
            atualizado = datetime.fromisoformat(cache["atualizado"])
            if (datetime.now() - atualizado).total_seconds() < 900:
                vagas = [v for v in cache["vagas"] if v["score"] >= min_score]
                return {
                    "fonte": "cache",
                    "atualizado": cache["atualizado"],
                    "total": len(vagas),
                    "vagas": vagas
                }
        except Exception:
            pass

    vagas = await buscar_vagas_vagasmoz(perfil)
    filtradas = [v for v in vagas if v["score"] >= min_score]
    return {
        "fonte": "vagasmoz.com",
        "atualizado": datetime.now().isoformat(),
        "total": len(filtradas),
        "vagas": filtradas
    }


@app.get("/api/candidaturas")
async def listar_candidaturas(estado: Optional[str] = None):
    cands = get_candidaturas()
    if estado:
        cands = [c for c in cands if c.get("estado") == estado]
    return cands


@app.post("/api/candidaturas")
async def criar_candidatura(data: CandidaturaCreate):
    cands = get_candidaturas()
    if any(c.get("vaga_id") == data.vaga_id for c in cands):
        raise HTTPException(status_code=400, detail="Já existe candidatura para esta vaga")

    perfil = get_perfil()
    vaga_dict = data.model_dump()

    nova = {
        "id": f"cand_{int(datetime.now().timestamp() * 1000)}",
        "vaga_id": data.vaga_id,
        "titulo": data.titulo,
        "empresa": data.empresa,
        "local": data.local,
        "score": data.score,
        "url": data.url,
        "descricao": data.descricao,
        "estado": "preparada",
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "cv_adaptado": gerar_cv_adaptado(vaga_dict, perfil),
        "carta": gerar_carta(vaga_dict, perfil)
    }
    cands.insert(0, nova)
    save_candidaturas(cands)
    return nova


@app.patch("/api/candidaturas/{cand_id}")
async def atualizar_candidatura(cand_id: str, data: CandidaturaUpdate):
    cands = get_candidaturas()
    for c in cands:
        if c["id"] == cand_id:
            c["estado"] = data.estado
            if data.estado == "enviada":
                c["data_envio"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            save_candidaturas(cands)
            return c
    raise HTTPException(status_code=404, detail="Candidatura não encontrada")


@app.get("/api/stats")
async def estatisticas():
    cache = load_json(VAGAS_CACHE_FILE, {})
    vagas = cache.get("vagas", [])
    cands = get_candidaturas()
    return {
        "vagas_total": len(vagas),
        "compativeis": len([v for v in vagas if v.get("score", 0) >= 70]),
        "preparadas": len([c for c in cands if c.get("estado") == "preparada"]),
        "enviadas": len([c for c in cands if c.get("estado") in ("enviada", "entrevista")]),
        "entrevistas": len([c for c in cands if c.get("estado") == "entrevista"]),
    }


# ---------------------- Frontend simples ----------------------
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Candidatura Fácil V4</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-800">
  <div class="max-w-3xl mx-auto p-4 pb-20">
    <header class="mb-6">
      <h1 class="text-2xl font-bold text-blue-700">Candidatura Fácil <span class="text-slate-500 text-lg">V4</span></h1>
      <p class="text-sm text-slate-500">Vagas reais de vagasmoz.com + CV e carta personalizados</p>
    </header>

    <!-- Perfil -->
    <section class="bg-white rounded-xl border p-4 mb-4">
      <h2 class="font-semibold mb-3">O teu perfil</h2>
      <div class="grid gap-2 text-sm">
        <input id="nome" placeholder="Nome completo" class="border rounded-lg px-3 py-2" />
        <input id="cargo" placeholder="Cargo / Título profissional" class="border rounded-lg px-3 py-2" />
        <input id="local" placeholder="Localização (ex: Maputo)" class="border rounded-lg px-3 py-2" />
        <input id="email" placeholder="Email" class="border rounded-lg px-3 py-2" />
        <input id="telefone" placeholder="Telefone" class="border rounded-lg px-3 py-2" />
        <input id="formacao" placeholder="Formação" class="border rounded-lg px-3 py-2" />
        <input id="skills" placeholder="Competências (separadas por ; )" class="border rounded-lg px-3 py-2" />
        <textarea id="experiencia_texto" placeholder="Experiência profissional" class="border rounded-lg px-3 py-2" rows="2"></textarea>
        <textarea id="resumo" placeholder="Resumo profissional (opcional)" class="border rounded-lg px-3 py-2" rows="2"></textarea>
        <button onclick="guardarPerfil()" class="bg-blue-600 text-white rounded-lg py-2 font-medium">Guardar perfil</button>
      </div>
    </section>

    <!-- Ações -->
    <div class="flex gap-2 mb-4">
      <button onclick="procurarVagas()" class="flex-1 bg-blue-600 text-white rounded-xl py-3 font-medium">Procurar Vagas</button>
      <button onclick="carregarCandidaturas()" class="flex-1 bg-slate-700 text-white rounded-xl py-3 font-medium">Candidaturas</button>
    </div>

    <div id="status" class="text-sm text-slate-500 mb-4"></div>

    <!-- Lista de vagas -->
    <div id="listaVagas" class="space-y-3 mb-8"></div>

    <!-- Candidaturas -->
    <div id="listaCands" class="space-y-3"></div>
  </div>

  <script>
    const API = '';

    async function api(path, opts = {}) {
      const res = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      return res.json();
    }

    async function carregarPerfil() {
      const p = await api('/api/perfil');
      document.getElementById('nome').value = p.nome || '';
      document.getElementById('cargo').value = p.cargo || '';
      document.getElementById('local').value = p.local || '';
      document.getElementById('email').value = p.email || '';
      document.getElementById('telefone').value = p.telefone || '';
      document.getElementById('formacao').value = p.formacao || '';
      document.getElementById('skills').value = p.skills || '';
      document.getElementById('experiencia_texto').value = p.experiencia_texto || '';
      document.getElementById('resumo').value = p.resumo || '';
    }

    async function guardarPerfil() {
      const body = {
        nome: document.getElementById('nome').value,
        cargo: document.getElementById('cargo').value,
        local: document.getElementById('local').value,
        email: document.getElementById('email').value,
        telefone: document.getElementById('telefone').value,
        formacao: document.getElementById('formacao').value,
        skills: document.getElementById('skills').value,
        experiencia_texto: document.getElementById('experiencia_texto').value,
        resumo: document.getElementById('resumo').value,
        experiencia: 1,
        min_score: 25
      };
      await api('/api/perfil', { method: 'POST', body: JSON.stringify(body) });
      document.getElementById('status').textContent = 'Perfil guardado!';
    }

    async function procurarVagas() {
      document.getElementById('status').textContent = 'A procurar vagas no vagasmoz.com...';
      document.getElementById('listaVagas').innerHTML = '';
      try {
        const data = await api('/api/vagas?forcar=true');
        document.getElementById('status').textContent = `${data.total} vagas encontradas (${data.fonte})`;
        const el = document.getElementById('listaVagas');
        el.innerHTML = data.vagas.map(v => `
          <div class="bg-white border rounded-xl p-4">
            <div class="flex justify-between items-start gap-2">
              <div>
                <h3 class="font-semibold">${v.titulo}</h3>
                <p class="text-sm text-slate-600">${v.empresa} · ${v.local}</p>
                <p class="text-xs text-slate-400 mt-1 line-clamp-2">${v.descricao?.slice(0,140) || ''}</p>
              </div>
              <div class="text-center shrink-0">
                <div class="w-12 h-12 rounded-lg flex items-center justify-center text-white font-bold text-sm
                  ${v.score >= 70 ? 'bg-emerald-500' : v.score >= 45 ? 'bg-amber-500' : 'bg-slate-400'}">
                  ${v.score}%
                </div>
              </div>
            </div>
            <div class="mt-3 flex gap-2">
              <a href="${v.url}" target="_blank" class="text-sm text-blue-600">Ver vaga</a>
              <button onclick='preparar(${JSON.stringify(v)})' class="text-sm bg-amber-500 text-white px-3 py-1 rounded-lg">Preparar CV + Carta</button>
            </div>
          </div>
        `).join('');
      } catch (e) {
        document.getElementById('status').textContent = 'Erro: ' + e.message;
      }
    }

    async function preparar(v) {
      try {
        const cand = await api('/api/candidaturas', {
          method: 'POST',
          body: JSON.stringify({
            vaga_id: v.id,
            titulo: v.titulo,
            empresa: v.empresa,
            local: v.local,
            score: v.score,
            url: v.url,
            descricao: v.descricao || ''
          })
        });
        alert('Candidatura preparada!\\n\\nVai à secção Candidaturas para ver o CV e a carta.');
        carregarCandidaturas();
      } catch (e) {
        alert(e.message);
      }
    }

    async function carregarCandidaturas() {
      const cands = await api('/api/candidaturas');
      const el = document.getElementById('listaCands');
      if (!cands.length) {
        el.innerHTML = '<p class="text-slate-400 text-sm">Nenhuma candidatura preparada ainda.</p>';
        return;
      }
      el.innerHTML = '<h2 class="font-semibold text-lg mb-2">Candidaturas preparadas</h2>' + cands.map(c => `
        <div class="bg-white border rounded-xl p-4 mb-3">
          <h3 class="font-semibold">${c.titulo}</h3>
          <p class="text-sm text-slate-600">${c.empresa} · Score ${c.score}%</p>
          <details class="mt-2">
            <summary class="text-sm text-blue-600 cursor-pointer">Ver CV adaptado</summary>
            <pre class="text-xs bg-slate-50 p-3 rounded mt-1 whitespace-pre-wrap">${c.cv_adaptado}</pre>
          </details>
          <details class="mt-2">
            <summary class="text-sm text-blue-600 cursor-pointer">Ver Carta de Motivação</summary>
            <pre class="text-xs bg-slate-50 p-3 rounded mt-1 whitespace-pre-wrap">${c.carta}</pre>
          </details>
        </div>
      `).join('');
    }

    carregarPerfil();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
