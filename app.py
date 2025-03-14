from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import pandas as pd
import os
import json
import uuid
import numpy as np
from datetime import datetime
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this to a random secret key
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv', 'xls', 'xlsx'}

# Set up logging
logging.basicConfig(level=logging.DEBUG, filename='app.log', 
                    format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Database initialization
def init_db():
    conn = sqlite3.connect('dashboard.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS dashboards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        config TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        hashed_password = generate_password_hash(password)
        
        conn = sqlite3.connect('dashboard.db')
        cursor = conn.cursor()
        
        try:
            cursor.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                          (username, email, hashed_password))
            conn.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists!', 'error')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('dashboard.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('dashboard.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name, created_at FROM dashboards WHERE user_id = ? ORDER BY created_at DESC", 
                  (session['user_id'],))
    dashboards = cursor.fetchall()
    conn.close()
    
    return render_template('dashboard.html', dashboards=dashboards)

@app.route('/create', methods=['GET', 'POST'])
def create_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = str(uuid.uuid4()) + '_' + file.filename
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            session['file_path'] = file_path
            
            sheets = []
            if file.filename.endswith(('.xls', '.xlsx')):
                xls = pd.ExcelFile(file_path)
                sheets = xls.sheet_names
            
            return render_template('create_dashboard.html', filename=file.filename, sheets=sheets)
    
    return render_template('upload.html')

@app.route('/get_columns', methods=['POST'])
def get_columns():
    if 'user_id' not in session or 'file_path' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    file_path = session['file_path']
    sheet_name = request.json.get('sheet_name', None)
    
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
        
        columns = df.columns.tolist()
        sample_data = df.head(5).to_dict('records')
        unique_values = {col: [str(val) for val in df[col].dropna().unique().tolist()] for col in columns}
        
        return jsonify({
            'columns': columns,
            'sample_data': sample_data,
            'unique_values': unique_values
        })
    except Exception as e:
        logger.error(f"Error in get_columns: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_column_values', methods=['POST'])
def get_column_values():
    if 'user_id' not in session or 'file_path' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    file_path = session['file_path']
    data = request.json
    sheet_name = data.get('sheet_name')
    column_name = data.get('column_name')
    
    if not column_name:
        return jsonify({'values': []})
    
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
        
        if column_name in df.columns:
            values = df[column_name].dropna().unique().tolist()
            values = [str(val) for val in values]
            return jsonify({'values': values})
        else:
            return jsonify({'error': 'Column not found'}), 404
    except Exception as e:
        logger.error(f"Error in get_column_values: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/save_dashboard', methods=['POST'])
def save_dashboard():
    if 'user_id' not in session or 'file_path' not in session:
        logger.warning("Unauthorized access attempt to save_dashboard")
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    logger.debug(f"Received dashboard data: {json.dumps(data, indent=2)}")
    
    dashboard_name = data.get('dashboard_name')
    if not dashboard_name:
        logger.error("Missing dashboard_name")
        return jsonify({'error': 'Dashboard name is required'}), 400
    
    try:
        dashboard_config = json.dumps(data)
        file_path = session['file_path']
        
        conn = sqlite3.connect('dashboard.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO dashboards (user_id, name, config, file_path) VALUES (?, ?, ?, ?)",
            (session['user_id'], dashboard_name, dashboard_config, file_path)
        )
        conn.commit()
        dashboard_id = cursor.lastrowid
        
        logger.info(f"Dashboard saved successfully with ID: {dashboard_id}")
        return jsonify({
            'success': True,
            'dashboard_id': dashboard_id
        })
    except sqlite3.Error as e:
        logger.error(f"Database error in save_dashboard: {str(e)}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Unexpected error in save_dashboard: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/view_dashboard/<int:dashboard_id>')
def view_dashboard(dashboard_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('dashboard.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT name, config, file_path FROM dashboards WHERE id = ? AND user_id = ?",
        (dashboard_id, session['user_id'])
    )
    dashboard = cursor.fetchone()
    conn.close()
    
    if not dashboard:
        flash('Dashboard not found or access denied', 'error')
        return redirect(url_for('dashboard'))
    
    name, config, file_path = dashboard
    config = json.loads(config)
    filename = os.path.basename(file_path).split('_', 1)[1]  # Extract original filename
    
    return render_template('view_dashboard.html', 
                          dashboard_name=name, 
                          dashboard_config=config,
                          dashboard_id=dashboard_id,
                          filename=filename)

@app.route('/get_dashboard_data/<int:dashboard_id>')
def get_dashboard_data(dashboard_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = sqlite3.connect('dashboard.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT config, file_path FROM dashboards WHERE id = ? AND user_id = ?",
        (dashboard_id, session['user_id'])
    )
    dashboard = cursor.fetchone()
    conn.close()
    
    if not dashboard:
        return jsonify({'error': 'Dashboard not found or access denied'}), 404
    
    config, file_path = dashboard
    config = json.loads(config)
    
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            sheet_name = config.get('sheet_name')
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
        
        graphs_data = []
        for graph in config.get('graphs', []):
            graph_type = graph.get('type')
            x_axis = graph.get('x_axis')
            y_axis = graph.get('y_axis')
            filter_column = graph.get('filter_column')
            filter_values = graph.get('filter_values', [])
            aggregation = graph.get('aggregation')
            color = graph.get('color', '#3498db')
            
            filtered_df = df.copy()
            if filter_column and filter_values and filter_column in filtered_df.columns:
                filtered_df = filtered_df[filtered_df[filter_column].astype(str).isin([str(val) for val in filter_values])]
            
            if filtered_df.empty:
                graph_data = {
                    'name': graph.get('name'),
                    'type': graph_type,
                    'x': [],
                    'y': [],
                    'color': color,
                    'empty': True
                }
                if graph_type in ['pie', 'donut']:
                    graph_data['labels'] = []
                    graph_data['values'] = []
                elif graph_type == 'number':
                    graph_data['value'] = 0
                graphs_data.append(graph_data)
                continue
            
            # Handle aggregation
            if aggregation and x_axis and y_axis and x_axis in filtered_df.columns and y_axis in filtered_df.columns:
                agg_df = filtered_df[[x_axis, y_axis]].dropna()
                if aggregation == 'sum':
                    result = agg_df.groupby(x_axis, as_index=False)[y_axis].sum()
                elif aggregation == 'count':
                    result = agg_df.groupby(x_axis, as_index=False)[y_axis].count()
                elif aggregation == 'avg':
                    result = agg_df.groupby(x_axis, as_index=False)[y_axis].mean()
                elif aggregation == 'min':
                    result = agg_df.groupby(x_axis, as_index=False)[y_axis].min()
                elif aggregation == 'max':
                    result = agg_df.groupby(x_axis, as_index=False)[y_axis].max()
                else:
                    result = agg_df
            elif x_axis in filtered_df.columns or y_axis in filtered_df.columns:
                result = filtered_df[[col for col in [x_axis, y_axis] if col in filtered_df.columns]].dropna()
            else:
                result = filtered_df
            
            # Prepare graph data
            graph_data = {
                'name': graph.get('name'),
                'type': graph_type,
                'x': ([float(x) if pd.api.types.is_numeric_dtype(type(x)) else str(x) 
                       for x in result[x_axis].tolist()] if x_axis in result.columns else []) if x_axis else [],
                'y': ([float(y) if pd.api.types.is_numeric_dtype(type(y)) else str(y) 
                       for y in result[y_axis].tolist()] if y_axis in result.columns else []) if y_axis else [],
                'color': color
            }
            
            # Special handling for specific graph types
            if graph_type in ['pie', 'donut']:
                graph_data['labels'] = graph_data.pop('x')
                graph_data['values'] = graph_data.pop('y')
            elif graph_type == 'histogram' and x_axis:
                graph_data['x'] = [float(x) if pd.api.types.is_numeric_dtype(type(x)) else x 
                                  for x in filtered_df[x_axis].dropna().tolist()]
                graph_data.pop('y', None)
            elif graph_type == 'distribution' and x_axis:
                graph_data['x'] = [float(x) if pd.api.types.is_numeric_dtype(type(x)) else x 
                                  for x in filtered_df[x_axis].dropna().tolist()]
                graph_data.pop('y', None)
            elif graph_type == 'number' and y_axis and y_axis in filtered_df.columns:
                if aggregation:
                    if aggregation == 'sum':
                        value = filtered_df[y_axis].sum()
                    elif aggregation == 'count':
                        value = filtered_df[y_axis].count()
                    elif aggregation == 'avg':
                        value = filtered_df[y_axis].mean()
                    elif aggregation == 'min':
                        value = filtered_df[y_axis].min()
                    elif aggregation == 'max':
                        value = filtered_df[y_axis].max()
                    else:
                        value = filtered_df[y_axis].iloc[0] if not filtered_df[y_axis].empty else 0
                else:
                    value = filtered_df[y_axis].iloc[0] if not filtered_df[y_axis].empty else 0
                graph_data['value'] = float(value) if pd.api.types.is_numeric_dtype(type(value)) else str(value)
            elif graph_type == 'gauge' and y_axis and y_axis in filtered_df.columns:
                value = float(filtered_df[y_axis].iloc[0]) if not filtered_df[y_axis].empty else 0
                graph_data['value'] = value
            
            graphs_data.append(graph_data)
        
        return jsonify({
            'success': True,
            'graphs': graphs_data
        })
    except Exception as e:
        logger.error(f"Error in get_dashboard_data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/delete_dashboard/<int:dashboard_id>', methods=['POST'])
def delete_dashboard(dashboard_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = sqlite3.connect('dashboard.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT file_path FROM dashboards WHERE id = ? AND user_id = ?",
            (dashboard_id, session['user_id'])
        )
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'error': 'Dashboard not found or access denied'}), 404
        
        file_path = result[0]
        
        cursor.execute(
            "DELETE FROM dashboards WHERE id = ? AND user_id = ?",
            (dashboard_id, session['user_id'])
        )
        conn.commit()
        
        cursor.execute(
            "SELECT COUNT(*) FROM dashboards WHERE file_path = ?",
            (file_path,)
        )
        count = cursor.fetchone()[0]
        
        if count == 0 and os.path.exists(file_path):
            os.remove(file_path)
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error in delete_dashboard: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)