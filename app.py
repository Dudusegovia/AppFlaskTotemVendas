import sqlite3
import os
import json
import shutil
from datetime import datetime
from threading import Thread
import time
from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================
# SISTEMA DE BACKUP
# ==========================
BACKUP_FOLDER = 'backups'
BACKUP_INTERVAL = 3600  # 1 hora
MAX_BACKUPS = 48  # Últimos 2 dias

def criar_pasta_backup():
    if not os.path.exists(BACKUP_FOLDER):
        os.makedirs(BACKUP_FOLDER)
        print(f"📁 Pasta de backups criada: {BACKUP_FOLDER}")

def fazer_backup():
    try:
        criar_pasta_backup()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        db_files = {
            'menu': MENU_DB_PATH,
            'pedidos': PEDIDOS_DB_PATH,
            'config': CONFIG_DB_PATH
        }
        
        for nome, arquivo in db_files.items():
            if os.path.exists(arquivo):
                backup_filename = f"{nome}_backup_{timestamp}.db"
                backup_path = os.path.join(BACKUP_FOLDER, backup_filename)
                shutil.copy2(arquivo, backup_path)
                tamanho_mb = os.path.getsize(backup_path) / (1024 * 1024)
                print(f"✅ Backup: {backup_filename} ({tamanho_mb:.2f} MB)")
        
        limpar_backups_antigos()
        return True
    except Exception as e:
        print(f"❌ Erro ao fazer backup: {e}")
        return False

def limpar_backups_antigos():
    try:
        arquivos = []
        for arquivo in os.listdir(BACKUP_FOLDER):
            if arquivo.endswith('.db'):
                caminho = os.path.join(BACKUP_FOLDER, arquivo)
                arquivos.append((caminho, os.path.getmtime(caminho)))
        
        arquivos.sort(key=lambda x: x[1], reverse=True)
        
        if len(arquivos) > MAX_BACKUPS:
            for arquivo, _ in arquivos[MAX_BACKUPS:]:
                os.remove(arquivo)
                print(f"🗑️ Backup antigo removido: {os.path.basename(arquivo)}")
    except Exception as e:
        print(f"⚠️ Erro ao limpar backups: {e}")

def backup_automatico():
    print(f"🔄 Backup automático iniciado (a cada {BACKUP_INTERVAL/60:.0f} min)")
    while True:
        time.sleep(BACKUP_INTERVAL)
        print(f"\n🕒 {datetime.now().strftime('%H:%M:%S')} - Backup automático...")
        fazer_backup()

def iniciar_backup_automatico():
    # ✅ Guard para evitar duplicação no reloader do Flask
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    
    print(f"\n{'='*50}")
    print("💾 Fazendo backup inicial...")
    print(f"{'='*50}")
    fazer_backup()
    backup_thread = Thread(target=backup_automatico, daemon=True)
    backup_thread.start()

# ==========================
# CONFIGURAÇÃO DO FLASK
# ==========================
app = Flask(__name__, static_folder='public', static_url_path='', template_folder='public')

# ✅ CORS restrito à mesma origem (ou específico em produção)
CORS(app, supports_credentials=True, origins=os.environ.get('CORS_ORIGINS', '*').split(','))

# ✅ SECRET_KEY de variável de ambiente
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-CHANGE-IN-PRODUCTION-' + os.urandom(24).hex())
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

UPLOAD_FOLDER = os.path.join(app.root_path, 'public', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

MENU_DB_PATH = 'sorveteria.db'
PEDIDOS_DB_PATH = 'pedidos.db'
CONFIG_DB_PATH = 'config.db'

# ✅ Senha admin de variável de ambiente
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'sorvete123'))

# ==========================
# FUNÇÕES DE CONEXÃO
# ==========================
def get_db(path, timeout=10.0):
    """
    Retorna conexão SQLite com:
    - PRAGMA foreign_keys=ON
    - journal_mode=WAL
    - timeout configurável
    """
    conn = sqlite3.connect(path, timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # ✅ Ativa foreign keys e WAL mode
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    
    return conn

# ==========================
# INICIALIZAÇÃO DOS BANCOS
# ==========================
def garantir_schema_base():
    """
    Garante que o esquema base existe antes de qualquer ALTER TABLE.
    """
    # Menu DB
    conn_menu = get_db(MENU_DB_PATH)
    cursor_menu = conn_menu.cursor()
    
    cursor_menu.execute('''
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    ''')
    
    cursor_menu.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            preco REAL NOT NULL,
            imagem TEXT,
            categoria_id INTEGER,
            FOREIGN KEY (categoria_id) REFERENCES categorias(id)
        )
    ''')
    
    cursor_menu.execute('''
        CREATE TABLE IF NOT EXISTS adicionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            preco REAL NOT NULL,
            categoria_id INTEGER,
            FOREIGN KEY (categoria_id) REFERENCES categorias(id)
        )
    ''')
    
    conn_menu.commit()
    conn_menu.close()
    
    # Pedidos DB
    conn_pedidos = get_db(PEDIDOS_DB_PATH)
    cursor_pedidos = conn_pedidos.cursor()
    
    cursor_pedidos.execute('''
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_nome TEXT NOT NULL,
            tipo_pedido TEXT NOT NULL,
            valor_total REAL NOT NULL DEFAULT 0,
            data_hora TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'recebido'
        )
    ''')
    
    cursor_pedidos.execute('''
        CREATE TABLE IF NOT EXISTS itens_pedido (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            produto_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            valor_unitario REAL NOT NULL,
            FOREIGN KEY (pedido_id) REFERENCES pedidos(id)
        )
    ''')
    
    conn_pedidos.commit()
    conn_pedidos.close()
    
    # Config DB
    conn_config = get_db(CONFIG_DB_PATH)
    cursor_config = conn_config.cursor()
    
    cursor_config.execute('''
        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            descricao TEXT,
            tipo TEXT DEFAULT 'text'
        )
    ''')
    
    conn_config.commit()
    conn_config.close()
    
    print("✅ Esquema base garantido em todos os bancos")

def init_estoque_db():
    """
    Adiciona coluna estoque se não existir.
    """
    conn = get_db(MENU_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(produtos)")
        colunas = [col[1] for col in cursor.fetchall()]
        if 'estoque' not in colunas:
            cursor.execute('ALTER TABLE produtos ADD COLUMN estoque INTEGER DEFAULT 999')
            print("✅ Coluna estoque adicionada em produtos")
        
        cursor.execute("PRAGMA table_info(adicionais)")
        colunas = [col[1] for col in cursor.fetchall()]
        if 'estoque' not in colunas:
            cursor.execute('ALTER TABLE adicionais ADD COLUMN estoque INTEGER DEFAULT 999')
            print("✅ Coluna estoque adicionada em adicionais")
        
        conn.commit()
    except Exception as e:
        print(f"❌ Erro ao init estoque: {e}")
    finally:
        conn.close()

def init_pedidos_adicionais_db():
    """
    Cria tabelas de adicionais e acompanhamentos vendidos.
    """
    conn = get_db(PEDIDOS_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS adicionais_pedido (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_pedido_id INTEGER NOT NULL,
                adicional_nome TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 1,
                valor_unitario REAL NOT NULL,
                FOREIGN KEY (item_pedido_id) REFERENCES itens_pedido(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS acompanhamentos_vendidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id INTEGER NOT NULL,
                categoria_produto TEXT NOT NULL,
                nome_acompanhamento TEXT NOT NULL,
                quantidade INTEGER NOT NULL,
                valor_unitario REAL NOT NULL,
                valor_total REAL NOT NULL,
                data TEXT NOT NULL,
                hora TEXT NOT NULL,
                FOREIGN KEY (pedido_id) REFERENCES pedidos(id)
            )
        ''')
        
        conn.commit()
        print("✅ Tabelas de adicionais verificadas/criadas")
    except Exception as e:
        print(f"❌ Erro ao criar tabelas: {e}")
    finally:
        conn.close()

def init_config_db():
    """
    Inicializa configurações padrão.
    """
    conn = get_db(CONFIG_DB_PATH)
    cursor = conn.cursor()
    
    configs = [
        ('timeout_pagina2', '30', 'Timeout na tela de escolha (segundos)', 'number'),
        ('timeout_totem', '120', 'Timeout no totem (segundos)', 'number'),
        ('timeout_nome', '60', 'Timeout na tela de nome (segundos)', 'number'),
        ('mostrar_timer_apos', '30', 'Mostrar timer quando faltar X segundos', 'number'),
        ('max_inclusos', '3', 'Máximo de acompanhamentos inclusos', 'number'),
    ]
    
    for chave, valor, desc, tipo in configs:
        cursor.execute('''
            INSERT OR IGNORE INTO config (chave, valor, descricao, tipo)
            VALUES (?, ?, ?, ?)
        ''', (chave, valor, desc, tipo))
    
    conn.commit()
    conn.close()
    print("✅ Configurações inicializadas")

# ==========================
# HELPERS DE VALIDAÇÃO
# ==========================
def validar_json_request():
    """
    Valida que a requisição tem Content-Type: application/json
    """
    if request.method in ['POST', 'PUT', 'PATCH']:
        content_type = request.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            return False
    return True

def require_auth(f):
    """
    Decorator para rotas que exigem autenticação.
    """
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'message': 'Não autorizado'}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ==========================
# HELPERS DE ESTOQUE
# ==========================
def verificar_estoque_disponivel(itens):
    """
    Verifica se há estoque suficiente para todos os itens do pedido.
    Retorna (sucesso: bool, mensagem: str, faltantes: list)
    """
    conn_menu = get_db(MENU_DB_PATH)
    cursor = conn_menu.cursor()
    faltantes = []
    
    try:
        for item in itens:
            # Aceita 'produto_id' ou 'produto' (nome)
            produto_id = item.get('produto_id')
            produto_nome = item.get('produto', '').strip()
            quantidade = item.get('quantidade', 1)
            
            if produto_id:
                produto = cursor.execute(
                    "SELECT id, nome, estoque FROM produtos WHERE id = ?",
                    (produto_id,)
                ).fetchone()
            else:
                # Case-insensitive
                produto = cursor.execute(
                    "SELECT id, nome, estoque FROM produtos WHERE LOWER(nome) = LOWER(?)",
                    (produto_nome,)
                ).fetchone()
            
            if not produto:
                faltantes.append({
                    'item': produto_nome or f"ID {produto_id}",
                    'motivo': 'Produto não encontrado'
                })
                continue
            
            if produto['estoque'] < quantidade:
                faltantes.append({
                    'item': produto['nome'],
                    'disponivel': produto['estoque'],
                    'solicitado': quantidade
                })
            
            # Verificar adicionais
            for adicional_item in item.get('adicionais', []):
                adicional_nome = adicional_item.get('nome', '').strip()
                adicional_qtd = adicional_item.get('quantidade', 1)
                
                adicional = cursor.execute(
                    "SELECT nome, estoque FROM adicionais WHERE LOWER(nome) = LOWER(?)",
                    (adicional_nome,)
                ).fetchone()
                
                if adicional and adicional['estoque'] < adicional_qtd * quantidade:
                    faltantes.append({
                        'item': adicional['nome'],
                        'disponivel': adicional['estoque'],
                        'solicitado': adicional_qtd * quantidade
                    })
        
        if faltantes:
            mensagens = []
            for f in faltantes:
                if 'motivo' in f:
                    mensagens.append(f"{f['item']}: {f['motivo']}")
                else:
                    mensagens.append(
                        f"{f['item']}: disponível {f['disponivel']}, solicitado {f['solicitado']}"
                    )
            return False, "; ".join(mensagens), faltantes
        
        return True, "Estoque suficiente", []
    
    finally:
        conn_menu.close()

def decrementar_estoque_transacao(cursor_menu, itens):
    """
    Decrementa estoque dentro de uma transação.
    Lança exceção se algo falhar.
    """
    for item in itens:
        produto_id = item.get('produto_id')
        produto_nome = item.get('produto', '').strip()
        quantidade = item.get('quantidade', 1)
        
        if produto_id:
            cursor_menu.execute(
                "UPDATE produtos SET estoque = estoque - ? WHERE id = ?",
                (quantidade, produto_id)
            )
        else:
            cursor_menu.execute(
                "UPDATE produtos SET estoque = estoque - ? WHERE LOWER(nome) = LOWER(?)",
                (quantidade, produto_nome)
            )
        
        # Decrementar adicionais
        for adicional_item in item.get('adicionais', []):
            adicional_nome = adicional_item.get('nome', '').strip()
            adicional_qtd = adicional_item.get('quantidade', 1)
            total_adicional = adicional_qtd * quantidade
            
            cursor_menu.execute(
                "UPDATE adicionais SET estoque = estoque - ? WHERE LOWER(nome) = LOWER(?)",
                (total_adicional, adicional_nome)
            )

def obter_categoria_produto(cursor_menu, produto_nome):
    """
    Busca a categoria de um produto pelo nome.
    """
    resultado = cursor_menu.execute("""
        SELECT c.nome 
        FROM produtos p
        JOIN categorias c ON p.categoria_id = c.id
        WHERE LOWER(p.nome) = LOWER(?)
    """, (produto_nome,)).fetchone()
    
    return resultado['nome'] if resultado else 'Outros'

# ==========================
# HELPERS DE PREÇO
# ==========================
def buscar_precos_batch(cursor_menu, nomes_adicionais):
    """
    Busca preços de múltiplos adicionais em uma única query.
    Retorna dict {nome: preco}
    """
    if not nomes_adicionais:
        return {}
    
    placeholders = ','.join('?' for _ in nomes_adicionais)
    query = f"SELECT nome, preco FROM adicionais WHERE LOWER(nome) IN ({','.join(['LOWER(?)'] * len(nomes_adicionais))})"
    
    resultados = cursor_menu.execute(query, nomes_adicionais).fetchall()
    
    # Case-insensitive dict
    precos = {}
    for row in resultados:
        precos[row['nome'].lower()] = row['preco']
    
    return precos

# ==========================
# ROTAS PÚBLICAS
# ==========================
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)

# ==========================
# API DE AUTENTICAÇÃO
# ==========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['logged_in'] = True
            return redirect('/admin.html')
        else:
            return render_template('login.html', error='Usuário ou senha inválidos')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

# ==========================
# API DE CONFIGURAÇÕES
# ==========================
@app.route('/api/config', methods=['GET'])
def get_config():
    conn = get_db(CONFIG_DB_PATH)
    try:
        configs = conn.execute("SELECT * FROM config").fetchall()
        return jsonify({row['chave']: dict(row) for row in configs})
    finally:
        conn.close()

@app.route('/api/config', methods=['POST'])
@require_auth
def save_config():
    if not validar_json_request():
        return jsonify({'message': 'Content-Type deve ser application/json'}), 400
    
    data = request.json
    conn = get_db(CONFIG_DB_PATH)
    try:
        for chave, valor in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)",
                (chave, str(valor))
            )
        conn.commit()
        return jsonify({'message': 'Configurações salvas'})
    finally:
        conn.close()

# ==========================
# API DE MENU (ADMIN)
# ==========================
@app.route('/api/menu', methods=['GET'])
def get_menu():
    conn = get_db(MENU_DB_PATH)
    try:
        categorias = conn.execute("SELECT * FROM categorias ORDER BY id").fetchall()
        produtos = conn.execute("SELECT * FROM produtos ORDER BY categoria_id, id").fetchall()
        adicionais = conn.execute("SELECT * FROM adicionais ORDER BY categoria_id, id").fetchall()
        
        return jsonify({
            'categorias': [dict(c) for c in categorias],
            'produtos': [dict(p) for p in produtos],
            'adicionais': [dict(a) for a in adicionais]
        })
    finally:
        conn.close()

@app.route('/api/menu', methods=['POST'])
@require_auth
def save_menu():
    if not validar_json_request():
        return jsonify({'message': 'Content-Type deve ser application/json'}), 400
    
    data = request.json
    conn_menu = get_db(MENU_DB_PATH)
    
    try:
        cursor = conn_menu.cursor()
        
        # Limpa tabelas, mas NÃO reseta sqlite_sequence
        cursor.execute("DELETE FROM adicionais")
        cursor.execute("DELETE FROM produtos")
        cursor.execute("DELETE FROM categorias")
        
        # Insere categorias
        for cat in data.get('categorias', []):
            cursor.execute(
                "INSERT INTO categorias (nome) VALUES (?)",
                (cat['nome'],)
            )
        
        # Insere produtos
        for prod in data.get('produtos', []):
            cursor.execute(
                "INSERT INTO produtos (nome, preco, imagem, categoria_id, estoque) VALUES (?, ?, ?, ?, ?)",
                (prod['nome'], prod['preco'], prod.get('imagem', ''), 
                 prod['categoria_id'], prod.get('estoque', 999))
            )
        
        # Insere adicionais
        for adic in data.get('adicionais', []):
            cursor.execute(
                "INSERT INTO adicionais (nome, preco, categoria_id, estoque) VALUES (?, ?, ?, ?)",
                (adic['nome'], adic['preco'], adic['categoria_id'], adic.get('estoque', 999))
            )
        
        conn_menu.commit()
        print("✅ Cardápio salvo com sucesso!")
        return jsonify({'message': 'Cardápio salvo'})
    
    except Exception as e:
        conn_menu.rollback()
        print(f"❌ Erro ao salvar cardápio: {e}")
        return jsonify({'message': f'Erro: {str(e)}'}), 500
    
    finally:
        conn_menu.close()

@app.route('/api/upload', methods=['POST'])
@require_auth
def upload_imagem():
    if 'file' not in request.files:
        return jsonify({'message': 'Nenhum arquivo'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'Nenhum arquivo selecionado'}), 400
    
    if file:
        # Remove arquivo antigo se houver
        old_file = request.form.get('old_file')
        if old_file:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_file)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    print(f"🗑️ Imagem antiga removida: {old_file}")
                except Exception as e:
                    print(f"⚠️ Erro ao remover imagem antiga: {e}")
        
        # Salva novo arquivo
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        url = f"/uploads/{filename}"
        return jsonify({'url': url})

# ==========================
# API DE PEDIDOS
# ==========================
@app.route('/api/pedidos', methods=['GET', 'POST'])
def handle_pedidos():
    if request.method == 'POST':
        if not validar_json_request():
            return jsonify({'message': 'Content-Type deve ser application/json'}), 400
        
        data = request.json
        itens = data.get('itens', [])
        cliente_nome = data.get('cliente_nome', 'Cliente').strip()
        tipo_pedido = data.get('tipo_pedido', 'agora')
        
        if not itens:
            return jsonify({'message': 'Pedido vazio'}), 400
        
        if not cliente_nome or len(cliente_nome) < 2:
            return jsonify({'message': 'Nome do cliente inválido'}), 400
        
        # ✅ VERIFICA ESTOQUE ANTES DE PROCESSAR
        estoque_ok, mensagem, faltantes = verificar_estoque_disponivel(itens)
        if not estoque_ok:
            return jsonify({
                'message': f'Estoque insuficiente: {mensagem}',
                'faltantes': faltantes
            }), 409
        
        # ✅ TRANSAÇÃO ATÔMICA COMPLETA
        conn_pedidos = get_db(PEDIDOS_DB_PATH)
        conn_menu = get_db(MENU_DB_PATH)
        
        try:
            cursor_pedidos = conn_pedidos.cursor()
            cursor_menu = conn_menu.cursor()
            
            # Data/hora
            agora = datetime.now()
            data_str = agora.strftime('%Y-%m-%d')
            hora_str = agora.strftime('%H:%M:%S')
            data_hora_completa = agora.strftime('%Y-%m-%d %H:%M:%S')
            
            # ✅ CALCULA TOTAL CORRETO (produtos + adicionais)
            valor_total_pedido = 0.0
            
            # Coleta nomes de todos os adicionais para busca em batch
            todos_adicionais = []
            for item in itens:
                for adicional in item.get('adicionais', []):
                    nome_adic = adicional.get('nome', '').strip()
                    if nome_adic:
                        todos_adicionais.append(nome_adic)
            
            # Busca preços em batch
            precos_adicionais = buscar_precos_batch(cursor_menu, todos_adicionais)
            
            # Calcula total
            for item in itens:
                produto_nome = item.get('produto', '').strip()
                quantidade = item.get('quantidade', 1)
                
                # Preço do produto
                produto = cursor_menu.execute(
                    "SELECT preco FROM produtos WHERE LOWER(nome) = LOWER(?)",
                    (produto_nome,)
                ).fetchone()
                
                if produto:
                    valor_total_pedido += produto['preco'] * quantidade
                
                # Preço dos adicionais
                for adicional in item.get('adicionais', []):
                    nome_adic = adicional.get('nome', '').strip().lower()
                    qtd_adic = adicional.get('quantidade', 1)
                    
                    if nome_adic in precos_adicionais:
                        valor_total_pedido += precos_adicionais[nome_adic] * qtd_adic * quantidade
            
            # Insere pedido com valor correto
            cursor_pedidos.execute('''
                INSERT INTO pedidos (cliente_nome, tipo_pedido, valor_total, data_hora, status)
                VALUES (?, ?, ?, ?, 'recebido')
            ''', (cliente_nome, tipo_pedido, valor_total_pedido, data_hora_completa))
            
            pedido_id = cursor_pedidos.lastrowid
            
            # ✅ AGREGAÇÃO CORRETA: coleta TODOS os acompanhamentos
            acompanhamentos_por_categoria = {}
            
            # Insere itens e adicionais
            for item in itens:
                produto_nome = item.get('produto', '').strip()
                quantidade = item.get('quantidade', 1)
                
                produto = cursor_menu.execute(
                    "SELECT id, preco FROM produtos WHERE LOWER(nome) = LOWER(?)",
                    (produto_nome,)
                ).fetchone()
                
                if not produto:
                    raise ValueError(f"Produto não encontrado: {produto_nome}")
                
                cursor_pedidos.execute('''
                    INSERT INTO itens_pedido (pedido_id, produto_nome, quantidade, valor_unitario)
                    VALUES (?, ?, ?, ?)
                ''', (pedido_id, produto_nome, quantidade, produto['preco']))
                
                item_pedido_id = cursor_pedidos.lastrowid
                
                # Categoria do produto
                categoria_produto = obter_categoria_produto(cursor_menu, produto_nome)
                
                # Insere adicionais e agrega
                for adicional in item.get('adicionais', []):
                    nome_adic = adicional.get('nome', '').strip()
                    qtd_adic = adicional.get('quantidade', 1)
                    qtd_total = qtd_adic * quantidade
                    
                    nome_adic_lower = nome_adic.lower()
                    valor_unit = precos_adicionais.get(nome_adic_lower, 0.0)
                    
                    cursor_pedidos.execute('''
                        INSERT INTO adicionais_pedido 
                        (item_pedido_id, adicional_nome, quantidade, valor_unitario)
                        VALUES (?, ?, ?, ?)
                    ''', (item_pedido_id, nome_adic, qtd_total, valor_unit))
                    
                    # ✅ AGREGA PARA TODOS OS ITENS
                    if categoria_produto not in acompanhamentos_por_categoria:
                        acompanhamentos_por_categoria[categoria_produto] = {}
                    
                    if nome_adic not in acompanhamentos_por_categoria[categoria_produto]:
                        acompanhamentos_por_categoria[categoria_produto][nome_adic] = {
                            'quantidade': 0,
                            'valor_unitario': valor_unit
                        }
                    
                    acompanhamentos_por_categoria[categoria_produto][nome_adic]['quantidade'] += qtd_total
            
            # Grava agregação
            for categoria, acompanhamentos in acompanhamentos_por_categoria.items():
                for nome_acomp, dados in acompanhamentos.items():
                    qtd = dados['quantidade']
                    valor_unit = dados['valor_unitario']
                    valor_total_acomp = qtd * valor_unit
                    
                    cursor_pedidos.execute('''
                        INSERT INTO acompanhamentos_vendidos 
                        (pedido_id, categoria_produto, nome_acompanhamento, quantidade, 
                         valor_unitario, valor_total, data, hora)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (pedido_id, categoria, nome_acomp, qtd, valor_unit, 
                          valor_total_acomp, data_str, hora_str))
            
            # ✅ DECREMENTA ESTOQUE NA MESMA TRANSAÇÃO
            decrementar_estoque_transacao(cursor_menu, itens)
            
            # Commit em ambos os bancos
            conn_pedidos.commit()
            conn_menu.commit()
            
            print(f"✅ Pedido #{pedido_id} criado: {cliente_nome}, R$ {valor_total_pedido:.2f}")
            
            return jsonify({
                'message': 'Pedido recebido!',
                'pedidoId': pedido_id,
                'valorTotal': valor_total_pedido
            })
        
        except Exception as e:
            conn_pedidos.rollback()
            conn_menu.rollback()
            print(f"❌ Erro ao processar pedido: {e}")
            return jsonify({'message': f'Erro ao processar pedido: {str(e)}'}), 500
        
        finally:
            conn_pedidos.close()
            conn_menu.close()
    
    if request.method == 'GET':
        # ✅ MODO PÚBLICO: omite dados sensíveis
        modo_publico = request.args.get('public', '').lower() == 'true'
        
        status_filter = request.args.get('status', 'recebido').split(',')
        status_validos = ['recebido', 'pronto', 'retirado']
        status_filter = [s.strip() for s in status_filter if s.strip() in status_validos]
        if not status_filter:
            status_filter = ['recebido']
        
        conn = get_db(PEDIDOS_DB_PATH)
        try:
            placeholders = ','.join('?' for _ in status_filter)
            query = f"SELECT * FROM pedidos WHERE status IN ({placeholders}) ORDER BY id ASC"
            pedidos_rows = conn.execute(query, status_filter).fetchall()
            
            lista_pedidos = []
            for pedido in pedidos_rows:
                itens_rows = conn.execute(
                    "SELECT * FROM itens_pedido WHERE pedido_id = ?",
                    (pedido['id'],)
                ).fetchall()
                
                itens_completos = []
                for item in itens_rows:
                    item_dict = dict(item)
                    adicionais_rows = conn.execute(
                        "SELECT * FROM adicionais_pedido WHERE item_pedido_id = ?",
                        (item['id'],)
                    ).fetchall()
                    item_dict['adicionais'] = [dict(ad) for ad in adicionais_rows]
                    itens_completos.append(item_dict)
                
                pedido_dict = {
                    'id': pedido['id'],
                    'tipo_pedido': pedido['tipo_pedido'],
                    'status': pedido['status'],
                    'valor_total': pedido['valor_total'],
                    'data_hora': pedido['data_hora'],
                    'itens': itens_completos
                }
                
                # ✅ Omite cliente_nome em modo público
                if not modo_publico:
                    pedido_dict['cliente_nome'] = pedido['cliente_nome']
                
                lista_pedidos.append(pedido_dict)
            
            return jsonify(lista_pedidos)
        finally:
            conn.close()

@app.route('/api/pedidos/<int:pedido_id>/status', methods=['POST'])
@require_auth
def update_pedido_status(pedido_id):
    """
    ✅ PROTEGIDO: exige autenticação
    """
    if not validar_json_request():
        return jsonify({'message': 'Content-Type deve ser application/json'}), 400
    
    novo_status = request.json.get('status')
    if not novo_status or novo_status not in ['recebido', 'pronto', 'retirado']:
        return jsonify({'message': 'Status inválido'}), 400
    
    conn = get_db(PEDIDOS_DB_PATH)
    try:
        pedido = conn.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
        if not pedido:
            return jsonify({'message': 'Pedido não encontrado'}), 404
        
        conn.execute("UPDATE pedidos SET status = ? WHERE id = ?", (novo_status, pedido_id))
        conn.commit()
        
        print(f"✅ Pedido #{pedido_id}: {pedido['status']} → {novo_status}")
        return jsonify({'message': 'Status atualizado'})
    finally:
        conn.close()

# ==========================
# API DE RELATÓRIOS (ADMIN)
# ==========================
@app.route('/api/relatorios/acompanhamentos', methods=['GET'])
@require_auth
def get_acompanhamentos_vendidos():
    """
    Retorna relatório de acompanhamentos vendidos.
    """
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    categoria = request.args.get('categoria')
    
    conn = get_db(PEDIDOS_DB_PATH)
    try:
        query = "SELECT * FROM acompanhamentos_vendidos WHERE 1=1"
        params = []
        
        if data_inicio:
            query += " AND data >= ?"
            params.append(data_inicio)
        
        if data_fim:
            query += " AND data <= ?"
            params.append(data_fim)
        
        if categoria:
            query += " AND categoria_produto = ?"
            params.append(categoria)
        
        query += " ORDER BY data DESC, hora DESC"
        
        resultados = conn.execute(query, params).fetchall()
        return jsonify([dict(row) for row in resultados])
    finally:
        conn.close()

# ==========================
# API DE BACKUP (ADMIN)
# ==========================
@app.route('/api/backup/manual', methods=['POST'])
@require_auth
def backup_manual():
    sucesso = fazer_backup()
    if sucesso:
        return jsonify({'message': '✅ Backup criado!'})
    else:
        return jsonify({'message': '❌ Erro ao criar backup'}), 500

@app.route('/api/backup/listar', methods=['GET'])
@require_auth
def listar_backups_api():
    try:
        criar_pasta_backup()
        arquivos = []
        for arquivo in os.listdir(BACKUP_FOLDER):
            if arquivo.endswith('.db'):
                caminho = os.path.join(BACKUP_FOLDER, arquivo)
                tamanho_mb = os.path.getsize(caminho) / (1024 * 1024)
                data = datetime.fromtimestamp(os.path.getmtime(caminho))
                arquivos.append({
                    'arquivo': arquivo,
                    'tamanho_mb': round(tamanho_mb, 2),
                    'data': data.strftime('%Y-%m-%d %H:%M:%S')
                })
        arquivos.sort(key=lambda x: x['data'], reverse=True)
        return jsonify(arquivos)
    except Exception as e:
        return jsonify({'message': f'Erro: {str(e)}'}), 500

@app.route('/api/backup/download/<filename>')
@require_auth
def download_backup(filename):
    try:
        return send_from_directory(BACKUP_FOLDER, filename, as_attachment=True)
    except Exception as e:
        return jsonify({'message': f'Erro: {str(e)}'}), 404

# ==========================
# TRATAMENTO DE ERROS
# ==========================
@app.errorhandler(404)
def not_found(e):
    return jsonify({'message': 'Não encontrado'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'message': 'Erro interno'}), 500

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'message': 'Arquivo muito grande. Máximo 5MB.'}), 413

# ==========================
# INICIALIZAÇÃO
# ==========================
if __name__ == '__main__':
    print('=' * 50)
    print('🍦 SORVETERIA TUDBOM')
    print('=' * 50)
    print(f'📁 Uploads: {UPLOAD_FOLDER}')
    print(f'🗄️ DBs: {MENU_DB_PATH}, {PEDIDOS_DB_PATH}, {CONFIG_DB_PATH}')
    print(f'💾 Backups: {BACKUP_FOLDER}')
    print(f'👤 Admin: {ADMIN_USERNAME}')
    print(f'🔐 SECRET_KEY: {"[ENV]" if "SECRET_KEY" in os.environ else "[DEV]"}')
    print('=' * 50)
    
    # Garante esquema base antes de tudo
    garantir_schema_base()
    init_estoque_db()
    init_pedidos_adicionais_db()
    init_config_db()
    
    # Inicia backup automático
    iniciar_backup_automatico()
    
    print('=' * 50)
    print('🚀 http://localhost:4000')
    print('=' * 50)
    
    app.run(port=4000, debug=True)