import os
import subprocess
import yaml
import inquirer
from pymysql import connect as mysql_connect
from psycopg2 import connect as postgres_connect
import docker
from urllib.parse import urlparse
from datetime import datetime
import json
import socket

def get_db_connection(db_type, host, port, user, password, database):
    if db_type in ['mysql', 'mariadb']:
        return mysql_connect(host=host, port=port or 3306, user=user, password=password, database=database)
    elif db_type == 'postgres':
        return postgres_connect(host=host, port=port or 5432, user=user, password=password, dbname=database)
    else:
        raise ValueError("Unsupported DB type")

def list_databases(db_type, host, port, user, password):
    """List available databases on the instance."""
    try:
        if db_type in ['mysql', 'mariadb']:
            conn = mysql_connect(host=host, port=port or 3306, user=user, password=password)
            cursor = conn.cursor()
            cursor.execute("SHOW DATABASES;")
            dbs = [row[0] for row in cursor.fetchall() if row[0] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
            cursor.close()
            conn.close()
            return dbs
        elif db_type == 'postgres':
            conn = postgres_connect(host=host, port=port or 5432, user=user, password=password, dbname='postgres')
            cursor = conn.cursor()
            cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
            dbs = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return dbs
        else:
            raise ValueError("Unsupported DB type")
    except Exception:
        raise

def create_dump(db_type, host, port, user, password, database, dump_file):
    port_arg = f"-P {port}" if port else ""
    if db_type in ['mysql', 'mariadb']:
        password_arg = f"-p{password}" if password else ""
        cmd = f"mysqldump -h {host} {port_arg} -u {user} {password_arg} {database} > {dump_file}"
    elif db_type == 'postgres':
        cmd = f"pg_dump -h {host} {port_arg} -U {user} -d {database} -f {dump_file}"
        os.environ['PGPASSWORD'] = password
    else:
        raise ValueError("Unsupported DB type")
    subprocess.run(cmd, shell=True, check=True)

def create_docker_compose(db_type, db_name, port, container_name, user, password):
    compose = {
        'version': '3.8',
        'services': {
            'db': {
                'image': f'{db_type}:latest',
                'container_name': container_name,
                'ports': [f'{port}:3306' if db_type in ['mysql', 'mariadb'] else f'{port}:5432'],
                'environment': {
                    'MYSQL_ROOT_PASSWORD': 'rootpass' if db_type in ['mysql', 'mariadb'] else None,
                    'MYSQL_USER': user if db_type in ['mysql', 'mariadb'] else None,
                    'MYSQL_PASSWORD': password if db_type in ['mysql', 'mariadb'] else None,
                    'MYSQL_DATABASE': db_name if db_type in ['mysql', 'mariadb'] else None,
                    'POSTGRES_DB': db_name if db_type == 'postgres' else None,
                    'POSTGRES_USER': user if db_type == 'postgres' else None,
                    'POSTGRES_PASSWORD': password if db_type == 'postgres' else None,
                },
                'volumes': [
                    './data:/var/lib/mysql' if db_type in ['mysql', 'mariadb'] else './data:/var/lib/postgresql/data'
                ],
                'networks': ['web']
            }
        },
        'networks': {
            'web': {
                'external': True
            }
        }
    }
    # Remove None values
    compose['services']['db']['environment'] = {k: v for k, v in compose['services']['db']['environment'].items() if v is not None}
    return compose

def find_free_port(start_port):
    import socket
    port = start_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                port += 1

def generate_md(db_name, port, url):
    md_content = f"# Database Migration: {db_name}\n\n"
    md_content += f"**Exposed URL:** {url}:{port}\n\n"
    md_content += "Other details...\n"
    with open("bases_de_datos.md", "a") as f:
        f.write(md_content)

def wait_for_db_ready(db_type, container_name, db_name, user, password):
    import time
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            if db_type in ['mysql', 'mariadb']:
                cmd = f"mysql -u root -prootpass -e 'SELECT 1' {db_name}"
            elif db_type == 'postgres':
                os.environ['PGPASSWORD'] = password
                cmd = f"psql -U {user} -d {db_name} -c 'SELECT 1'"
            result = subprocess.run(["docker", "exec", container_name, "bash", "-c", cmd], capture_output=True, text=True)
            if result.returncode == 0:
                return True
        except:
            pass
        time.sleep(2)
    return False

def load_dump_into_container(db_type, container_name, dump_file, db_name, user, password):
    # Wait for db to be ready
    if not wait_for_db_ready(db_type, container_name, db_name, user, password):
        raise Exception("Database did not become ready in time")
    # Copy dump to container
    subprocess.run(["docker", "cp", dump_file, f"{container_name}:/tmp/dump.sql"], check=True)
    # Execute load command
    if db_type in ['mysql', 'mariadb']:
        cmd = f"mysql -u root -prootpass {db_name} < /tmp/dump.sql"
    elif db_type == 'postgres':
        os.environ['PGPASSWORD'] = password
        cmd = f"psql -U {user} -d {db_name} < /tmp/dump.sql"
    subprocess.run(["docker", "exec", container_name, "bash", "-c", cmd], check=True)
    # Ensure user permissions
    if db_type in ['mysql', 'mariadb']:
        grant_cmd = f"mysql -u root -prootpass -e \"ALTER USER '{user}'@'%' IDENTIFIED BY '{password}'; GRANT ALL PRIVILEGES ON *.* TO '{user}'@'%'; FLUSH PRIVILEGES;\""
    elif db_type == 'postgres':
        grant_cmd = f"psql -U {user} -d {db_name} -c \"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {user};\""
    subprocess.run(["docker", "exec", container_name, "bash", "-c", grant_cmd], check=True)

def main():
    # Paso 1: Preguntar el tipo de db a migrar
    db_type_question = [
        inquirer.List('db_type', message="Select DB type to migrate", choices=['mysql', 'mariadb', 'postgres']),
    ]
    db_type_answer = inquirer.prompt(db_type_question)
    db_type = db_type_answer['db_type']
    
    # Paso 2: Crear manifiesto.json si no existe
    if not os.path.exists('manifiesto.json'):
        with open('manifiesto.json', 'w') as f:
            json.dump({}, f)
    
    # Paso 3: Pedir url, usuario, contraseña de la db origen
    questions = [
        inquirer.Text('host', message="Enter DB host URL (e.g., localhost:3306)"),
        inquirer.Text('user', message="Enter DB user"),
        inquirer.Text('password', message="Enter DB password"),
    ]
    answers = inquirer.prompt(questions)
    
    parsed = urlparse(answers['host'])
    if parsed.scheme:
        host = parsed.hostname
        port = parsed.port
    else:
        if ':' in answers['host']:
            host, port_str = answers['host'].rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                host = answers['host']
                port = None
        else:
            host = answers['host']
            port = None
    if port is None:
        port = 3306 if db_type in ['mysql', 'mariadb'] else 5432
    user = answers['user']
    password = answers['password']
    
    # Paso 4: Consultar las bases de datos disponibles
    try:
        databases = list_databases(db_type, host, port, user, password)
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return
    
    # Paso 5: Mostrar selector de cursor para elegir la db a migrar
    db_question = [
        inquirer.List('database', message="Select database to migrate", choices=databases),
    ]
    db_answer = inquirer.prompt(db_question)
    database = db_answer['database']
    
    # Preguntar nombre del contenedor
    container_question = [
        inquirer.Text('container_name', message=f"Enter container name (default: {database}-db)", default=f"{database}-db"),
    ]
    container_answer = inquirer.prompt(container_question)
    container_name = container_answer['container_name']
    
    # Auto asignar puerto libre
    start_port = 3307 if db_type in ['mysql', 'mariadb'] else 5433
    exposed_port = find_free_port(start_port)
    
    # Paso 6: Generar un dump de la db seleccionada
    try:
        os.makedirs(database, exist_ok=True)
        os.makedirs(f"{database}/respaldos", exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dump_file = f"{database}/respaldos/{database}_{timestamp}.sql"
        create_dump(db_type, host, port, user, password, database, dump_file)
    except Exception as e:
        print(f"Error creating dump: {e}")
        return
    
    # Paso 7: Crear una carpeta con el nombre de la db seleccionada (ya hecho)
    
    # Paso 8: Dentro de la carpeta crear docker-compose.yml
    compose = create_docker_compose(db_type, database, exposed_port, container_name, user, password)
    with open(f"{database}/docker-compose.yml", "w") as f:
        yaml.dump(compose, f)
    
    # Paso 9: Crear un contenedor docker con la db seleccionada
    try:
        subprocess.run(["docker", "compose", "up", "-d"], cwd=database, check=True)
    except Exception as e:
        print(f"Error starting docker container: {e}")
        return
    
    # Paso 10: Cargar el dump en la nueva db del contenedor
    try:
        load_dump_into_container(db_type, container_name, dump_file, database, user, password)
    except Exception as e:
        print(f"Error loading dump: {e}")
        return
    
    # Paso 11: Agregar los datos de la nueva db en bases_de_datos.md
    url = "http://localhost"
    generate_md(database, exposed_port, url)
    
    # Guardar en manifiesto.json
    migration_date = datetime.now().isoformat()
    try:
        with open('manifiesto.json', 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if db_type not in data:
        data[db_type] = {}
    data[db_type][database] = {
        'host': host,
        'port': port,
        'user': user,
        'password': password,
        'container': container_name,
        'exposed_port': exposed_port,
        'migration_date': migration_date
    }
    with open('manifiesto.json', 'w') as f:
        json.dump(data, f, indent=4)
    
    # Paso 12: Al finalizar mostrar un resumen
    print("\n" + "="*50)
    print("🎉 MIGRACIÓN COMPLETADA EXITOSAMENTE 🎉")
    print("="*50)
    print(f"📊 Base de datos: {database}")
    print(f"🏗️  Tipo: {db_type}")
    print(f"🐳 Contenedor: {container_name}")
    print(f"🌐 URL expuesta: http://localhost:{exposed_port}")
    print(f"👤 Usuario: {user}")
    print(f"🔒 Password: {password}")
    print(f"📁 Archivo dump: {dump_file}")
    print(f"📅 Fecha de migración: {migration_date}")
    print(f"📝 Documento: bases_de_datos.md actualizado")
    print("="*50)
    print("💡 Para conectarte desde consola:")
    print(f"   mariadb -h localhost -P {exposed_port} -u {user} -p")
    print("   (Ingresa la password cuando se solicite)")
    print("="*50)

if __name__ == "__main__":
    main()
