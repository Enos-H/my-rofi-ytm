# 05 — Troubleshooting

Tabela sintoma → causa → correção. Ordene pelos itens marcados [frequente].

## Autenticação / API

| Sintoma | Causa provável | Correção |
|---|---|---|
| Notificação "Nenhum cookie do YouTube encontrado no Firefox..." | Nenhum cookie de youtube.com no perfil (ou perfil errado) | Checar `YTM_PROFILE`; abrir youtube.com logado; rodar `refresh_auth.py` |
| "Sessão do YouTube não encontrada no Firefox..." | Firefox deslogado do YouTube | Fazer login em youtube.com e tentar de novo (a recuperação é automática) |
| "Falha ao acessar a página do YouTube Music..." | Sem conexão / HTML mudou | Verificar rede; conferir se a página ainda expõe `DATASYNC_ID` |
| "No auth found. Run refresh_auth.py first" [frequente após limpeza] | `headers_auth.json` inexistente | Rodar `~/.config/rofi/scripts/ytm/refresh_auth.py` uma vez |
| Busca funciona, mas a notificação diz "Auth error - check Firefox login" | stderr do helper propagado | Ver o stderr direto: `ytm.py search "x"` no terminal |
| Campo da busca retorna vazio/silencioso (exit 0 sem saída) | Guard `if __name__ == "__main__": main()` removido do ytm.py | Restaurar o guard no fim do arquivo (lição de 06-history) |
| Error com "authuser" / conta errada nas listas | Conta index diferente no `x-goog-authuser` | Atualizar o `x-goog-authuser` no refresh_auth.py para o index correto |

## Playback (mpv / yt-dlp)

| Sintoma | Causa provável | Correção |
|---|---|---|
| mpv abre e fica 0% CPU, sem áudio ("HTTP error 403 Forbidden" no log) [frequente] | URL nasce sem `pot=` (PO Token) | Conferir as 3 `--ytdl-raw-options` do `play_url()`; confirmar plugin e deno abaixo |
| `yt-dlp -v` sem "PO Token Providers" | Plugin bgutil não carregado | Rodar yt-dlp do **venv** (`~/.local/share/ytm-venv/bin/yt-dlp -v`) — plugins pip NÃO existem para o yt-dlp do apt/binário |
| "No supported JavaScript runtime could be found" | deno ausente ou fora do PATH | `curl -fsSL https://deno.land/install.sh \| sh -s -- -y`; conferir `$HOME/.deno/bin` no PATH do `play_url()` |
| "web_music client https formats require a GVS PO Token... skipped" | sem cookies OU provider não ativo | `--cookies-from-browser` com o caminho do perfil snap; plugin verificado |
| "Signature solving failed... only images" | sem `remote-components=ejs:github` | Adicionar a flag ao `play_url()` |
| `python -m yt_dlp` ou yt-dlp global funciona, mpv não | mpv pegou o yt-dlp errado no PATH | O PATH do mpv deve ter o venv **primeiro**: `env PATH=venv:deno:$PATH` |
| Música toca, mas "only images" no `-F` | Cliente `web` (default) | Usar `player_client=web_music` |
| Erro ao tocar playlist privada | mpv sem cookies da conta | `cookies-from-browser=firefox:<perfil>` presente em `play_url()` |
| `Database is locked` (Firefox) | yt-dlp lendo cookies.sqlite com o Firefox aberto | Em geral o snap profile funciona com o Firefox aberto; se ocorrer: fechar o Firefox, ou exportar `cookies.txt` e usar `--cookies <arquivo>` |

## Depuração

```bash
# 1. Log do mpv com verbosidade (sem --no-terminal)
mpv --msg-level=all=status --no-video \
  --ytdl-raw-options="extractor-args=youtube:player_client=web_music" \
  --ytdl-raw-options="remote-components=ejs:github" \
  --ytdl-raw-options="cookies-from-browser=firefox:$HOME/snap/firefox/common/.mozilla/firefox/2b11ppm1.default" \
  'https://music.youtube.com/watch?v=<videoId>'

# 2. Ver provider de PO token
~/.local/share/ytm-venv/bin/yt-dlp -v 2>&1 | grep -i "PO Token"

# 3. Extração manual (URL da faixa + pot)
~/.local/share/ytm-venv/bin/yt-dlp -f bestaudio/best -g \
  --extractor-args "youtube:player_client=web_music" \
  --remote-components ejs:github \
  --cookies-from-browser "firefox:$HOME/snap/firefox/common/.mozilla/firefox/2b11ppm1.default" \
  'https://music.youtube.com/watch?v=<videoId>'
#  -> URL válida contém "pot="; se não tiver, o provider não está ativo

# 4. Auth manual
~/.local/share/ytm-venv/bin/python ~/.config/rofi/scripts/ytm/refresh_auth.py

# 5. UI completa
~/.config/hypr/UserScripts/RofiYtm.sh
```

## Checklist rápido (música não toca)

1. `ytm.py search "teste"` → retorna lista? (senão: auth, item Auth/API)
2. `yt-dlp -v \| grep "PO Token"` → provider presente? (senão: venv/plugin/deno)
3. Extração manual contém `pot=`? (senão: flags do mpv)
4. Teste de URL: `curl -sI "<url do passo 3>"` → 200? (senão: atualizar yt-dlp)