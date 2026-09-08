# Backup y restore aislado

**NO EJECUTADO** sobre datos reales. Procedimiento independiente de migraciones.
RPO objetivo inicial 24 h; RTO objetivo 4 h. Son objetivos, no mediciones ni SLA.
Después del ensayo registrar tiempos/bytes/recuentos y revisar objetivos.

## Inventario de recuperación

- Datos: public (recetas/ingredientes/pasos/colecciones/compra), private (recibos),
  foodiefy_imports (jobs, ledger, artifacts transitorios, controles), auth y metadata
  storage. No exportar temporales ni datos sintéticos en reportes operativos.
- **Objetos de recipe-images por separado**: SQL/metadata no contiene sus bytes.
  Inventario privado de claves, tamaño/checksum y vínculo owner/recipe, cifrado.
- Esquema/funciones/RLS/índices/migration history y roles no-login, membership de
  logins web/worker. Credenciales, claves JWT/proveedores, SMTP, OAuth, redirects,
  CA/TLS, dominios/DNS y configuración de Auth se recuperan del gestor de secretos
  y manifiestos de configuración. No asumir que un dump recrea esas integraciones.
- Backups administrados/PITR Supabase dependen del plan contratado; verificar
  ventana real. No presuponer backup de objetos por activar backup SQL.

## Captura manual

Usar cliente pg_dump/pg_restore compatible con la **versión real** del servidor,
preferiblemente misma mayor. Acceso de backup mínimo autorizado, TLS verify-full.
Configurar PGSERVICEFILE/PGPASSFILE fuera del repo (permisos 0600); el servicio
libpq `foodiefy_staging_backup` apunta al destino revisado sin password en argumentos.
Verificar hostname/proyecto/DB antes. No usar set -x ni imprimir esos archivos.
Coordinar ventana sin escrituras/borrrados y verificar consistencia DB-objetos;
la app no tiene un interruptor global de solo lectura entregado en esta fase.
Sin esa coordinación o versionado consistente de objetos no afirmar backup atómico.

```sh
umask 077
mkdir -p "$BACKUP_DIR/objects"
PGSERVICE=foodiefy_staging_backup pg_dump --format=custom --no-owner --file="$BACKUP_DIR/database.dump"
PGSERVICE=foodiefy_staging_backup pg_dumpall --roles-only --no-role-passwords > "$BACKUP_DIR/roles.sql"
supabase storage cp --linked --recursive ss:///recipe-images "$BACKUP_DIR/objects" > "$BACKUP_DIR/storage-copy.private.log" 2>&1
```

BACKUP_DIR debe ser ruta privada fuera del repo; antes de storage cp revisar que
supabase link sigue señalando **staging**. CLI 2.110.0 cp --recursive/--linked se
verificó por --help, no se ejecutó copia. Si el login no puede exportar managed
schemas/roles, utilizar backup/restore oficial Supabase con permisos aprobados;
no marcar dump parcial como completo. Leer salida privada de forma restringida.
Confirmar inventario auth/public/private/imports/storage y ownership de imágenes,
comprobar objetos faltantes = 0. El dump puede incluir hashes de contraseña Auth:
se considera secreto incluso si no contiene passwords en claro.

Cifrar antes de copia externa. Ejemplo age (herramienta elegida por propietario,
no instalada por esta fase), AGE_RECIPIENT es clave **pública** de recuperación:

```sh
tar -C "$BACKUP_DIR" -cf "$BACKUP_ARCHIVE" database.dump roles.sql objects
age --recipient "$AGE_RECIPIENT" --output "$BACKUP_ARCHIVE.age" "$BACKUP_ARCHIVE"
```

Guardar el ciphertext en almacenamiento externo aprobado, con cuenta/clave distinta
del proyecto y retención: 7 diarios, 4 semanales, 6 mensuales como propuesta inicial.
Copia offline de identidad age en gestor seguro; probar descifrado sin depender
del servidor perdido. Revisar eliminación de copias sin cifrar según política
local; no hay borrado automático de backups. Retención/replicación externa aún no
configuradas. Reportar solo fecha, checksum del ciphertext, recuentos agregados y
resultado; nunca dump, claves de objeto, emails, tokens ni cuentas sintéticas.

## Restore en destino nuevo y aislado

1. Crear **otro** proyecto/DB de laboratorio con versión compatible y Storage
   privado; mostrar y verificar su ref. Sin tráfico público/cron/worker/pagos.
   No usar producción ni sobrescribir staging activo. Restaurar secretos/roles
   de lab por canales aparte, jamás copiar credenciales productivas al móvil.
2. Definir servicio libpq `foodiefy_restore_lab` con CA y credenciales propias.
   Descifrar en directorio privado; verificar checksum y revisar TOC:

```sh
age --decrypt --identity "$AGE_IDENTITY_FILE" --output "$RESTORE_ARCHIVE" "$ENCRYPTED_BACKUP"
tar -xf "$RESTORE_ARCHIVE" -C "$RESTORE_DIR"
pg_restore --list "$RESTORE_DIR/database.dump" > "$RESTORE_DIR/restore.toc"
```

3. Revisar TOC contra destino: Supabase ya posee extensiones/schemas administrados;
   seguir su procedimiento oficial para Auth/Storage, excluir solo objetos managed
   incompatibles de la lista revisada. No restaurar roles superusuario/passwords ni
   asumir que --no-owner reproduce ownership de funciones; comparar propietarios y
   grants con las migraciones revisadas. Si hay conflicto, detener y rehacer lab,
   no añadir --clean contra un destino en uso.
4. Aplicar **solo al lab** la lista revisada con los roles esperados ya provisionados:

```sh
PGSERVICE=foodiefy_restore_lab pg_restore --exit-on-error --no-owner --use-list="$RESTORE_DIR/restore.toc" --dbname='service=foodiefy_restore_lab' "$RESTORE_DIR/database.dump"
supabase link --project-ref "$RESTORE_LAB_PROJECT_REF"
supabase storage cp --linked --recursive "$RESTORE_DIR/objects/recipe-images" ss:///recipe-images > "$RESTORE_DIR/storage-restore.private.log" 2>&1
```

La ruta local final del download debe comprobarse contra el inventario antes de
subir (CLI puede conservar directorios); no crear recipe-images/recipe-images por
error. No abrir bucket público para «arreglar» lectura. Verificar checksums/bytes
por objeto y que cada recipe.image_storage_path tiene objeto; SQL solo no basta.
5. Comparar recuentos por tabla/owner con manifiesto privado de backup y registros
   de tiempo; comprobar huérfanos=0, RLS habilitada, constraints/FKs válidas,
   revisión/tombstones/recibos. Verificar /v1 y funciones SECURITY INVOKER/grants.
   Probar lectura/modificación con JWT **reales de dos usuarios de lab**: B no ve
   receta, compra ni imagen de A. Los contadores admin no prueban RLS real.
6. Usar configuración Flutter **de lab** (HTTPS/key pública), iniciar sesión con
   usuario restaurado permitido y abrir una receta que incluya imagen privada.
   Probar refresco de URL firmada (3600 s). No reactivar imports/pagos durante restore.
7. Registrar RPO real observado, RTO medido, recuentos/imagen/A-B y fecha; solo al
   pasar autorizar otra operación de recuperación. El ensayo aquí es NO EJECUTADO.

Fuente: https://supabase.com/docs/guides/platform/backups y procedimiento de restore
de la versión/plan objetivo. No equivale a una promesa de recuperación verificada.
