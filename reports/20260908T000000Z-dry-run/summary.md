# Benchmark Foodiefy

Modo: dry_run. pendiente de medición.
Casos medidos: 0. Llamadas pagadas: 0.
Coste observado USD: desconocido/no medido.

Los resultados privados incluyen usage y costes por etapa, resultados originales, errores por etapa y revisión de fidelidad.
p50/p95 usan interpolación lineal. total_ms reconstruye etapas de la ruta; wall_ms mide ejecución con caché. No son equivalentes.

| Caso | Rutas | Bloqueos |
| --- | --- | --- |
| json_ld-01 | J | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| json_ld-02 | J | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| json_ld-03 | J | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| json_ld-04 | J | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| json_ld-05 | J | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| description-01 | A, B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| description-02 | A, B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| description-03 | A, B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| description-04 | A, B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| description-05 | A, B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| subtitles-01 | A, C, D | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| subtitles-02 | A, C, D | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| subtitles-03 | A, C, D | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| subtitles-04 | A, C, D | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| subtitles-05 | A, C, D | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| narrated-01 | B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| narrated-02 | B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| narrated-03 | B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| narrated-04 | B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| narrated-05 | B, C, D, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| visual-01 | C, F_frames, F_video | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| visual-02 | C, F_frames, F_video | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| visual-03 | C, F_frames, F_video | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| visual-04 | C, F_frames, F_video | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| visual-05 | C, F_frames, F_video | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| no_recipe-01 | A, C, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| no_recipe-02 | A, C, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| no_recipe-03 | A, C, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| no_recipe-04 | A, C, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |
| no_recipe-05 | A, C, E | processing_not_allowed, origin_license_missing, source_missing, human_reference_missing |

# Decisión IA · Fase 07

Fecha: 2026-09-08T13:22:00.121847+00:00. Dataset: pilot-30.pending.v1.

No cambia producción. Umbral: ≥5 casos por cohorte/ruta, todos revisados, ≥95% aceptados, cero errores graves y coste conocido.

| Cohorte | Ruta recomendada | Evidencia / calidad | p50 / p95 ms | Coste por caso aceptado USD | Fallback |
| --- | --- | --- | --- | --- | --- |
| json_ld | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |
| description | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |
| subtitles | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |
| narrated | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |
| visual | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |
| no_recipe | pendiente de medición | muestra insuficiente o umbral no superado | — | — | — |

Las rutas no medidas no quedan descartadas. Los pares B/C comparten STT; F es un experimento visual explícito, no una cascada automática.
Coste standalone atribuye STT compartido a cada ruta. Gasto observado global cuenta cada llamada una vez. Desconocido = null.
Groq opcional: no implementado ni medido. No se atribuye ventaja.
