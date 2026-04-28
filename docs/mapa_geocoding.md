# Mapa e Geocodificacao

## Opcao gratuita padrao

O app usa por padrao uma pilha sem chave obrigatoria:

- **Renderizacao:** MapLibre GL JS, com WebGL no Qt WebEngine.
- **Satelite:** Esri World Imagery.
- **Mapa claro:** tiles raster do OpenStreetMap.
- **Ruas/labels sobre satelite:** camadas de referencia da Esri para transporte e localidades, quando disponiveis.
- **Geocodificacao:** Nominatim/OpenStreetMap, com cache local e limite de 1 requisicao por segundo.

O Leaflet continua no projeto como fallback. Se o MapLibre nao carregar no Qt WebEngine, o app pode abrir `map_leaflet.html`.

## Diferenca para Mapbox

Mapbox entrega uma experiencia visual excelente, especialmente no estilo `Satellite Streets`, mas depende de token e pode gerar cobranca por uso. A alternativa MapLibre + Esri + OSM nao exige token do Mapbox e e adequada para uso diario quando a prioridade e reduzir risco de custo.

Mapbox permanece apenas como alternativa opcional/configuravel.

## Limites conhecidos

O OpenStreetMap oficial nao oferece camada de satelite. Por isso o satelite vem do Esri World Imagery.

Labels, ruas e POIs/comercios dependem da fonte gratuita escolhida. Na versao inicial, o app usa:

- Esri World Imagery para imagem;
- Esri World Transportation e World Boundaries and Places como referencias sobre o satelite;
- OpenStreetMap raster como camada clara alternativa com labels/POIs renderizados pelo proprio tile.

TODO: avaliar uma fonte vetorial gratuita e confiavel para labels/POIs em MapLibre sem token obrigatorio, respeitando politica de uso e atribuicao.

## Geocodificacao

Nominatim e o geocoder padrao. Ele e gratuito, mas tem limites importantes:

- usar `User-Agent` identificavel;
- limitar a 1 requisicao por segundo;
- usar cache;
- evitar bulk geocoding;
- aceitar que a precisao pode variar conforme a qualidade dos dados OSM.

O app normaliza buscas para Sao Carlos/SP/Brasil, salva resultados em cache por endereco normalizado e preserva coordenadas existentes sem recalcular.

ArcGIS permanece como fallback quando o Nominatim nao retorna candidatos.

## Politica de tiles

O app nao deve:

- fazer prefetch agressivo;
- fazer download em massa;
- baixar tiles offline de `tile.openstreetmap.org`;
- enviar headers `no-cache`;
- ocultar atribuicao.

O mapa deve mostrar atribuicoes visiveis para Esri, Maxar/Earthstar Geographics quando aplicavel, e OpenStreetMap contributors.

## Quando considerar provedor pago

Considere Mapbox ou Google quando:

- for essencial ter geocodificacao mais precisa e consistente;
- houver necessidade de autocomplete comercial robusto;
- POIs/comercios precisarem ser completos;
- a disponibilidade/SLAs forem mais importantes que custo zero.

Nesse caso, mantenha token, cota local e fallback gratuito ativos para evitar cobrancas inesperadas.
