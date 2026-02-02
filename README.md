# Migrate New Database

Herramienta para migrar bases de datos (MySQL, MariaDB o PostgreSQL) a contenedores Docker. Crea dumps de la base de datos origen, configura un contenedor Docker con la base de datos migrada y carga los datos.

## Instalación

1. Clona o descarga el repositorio.
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. O instala el paquete:
   ```bash
   pip install .
   ```

## Uso

Ejecuta el comando:

```bash
databases-migration
```

Sigue las instrucciones interactivas para seleccionar el tipo de base de datos, proporcionar credenciales y elegir la base de datos a migrar.

## Funcionalidades

- Lista bases de datos disponibles en la instancia origen.
- Crea un dump de la base de datos seleccionada.
- Genera un `docker-compose.yml` para el contenedor Docker.
- Inicia el contenedor y carga el dump.
- Actualiza `manifiesto.json` y `bases_de_datos.md` con los detalles de la migración.

## Dependencias

- PyYAML
- inquirer
- PyMySQL
- psycopg2-binary
- docker

## Archivos Generados

- `manifiesto.json`: Registro de migraciones realizadas.
- `bases_de_datos.md`: Documentación de las bases de datos migradas.
- Carpeta por base de datos con `docker-compose.yml` y respaldos.

## Notas

Asegúrate de tener Docker instalado y ejecutándose. El script asume permisos para ejecutar comandos Docker.
