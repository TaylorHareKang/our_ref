from flask import Flask, render_template, request, jsonify
import os
import logging
from datetime import datetime, timedelta
import sqlite3

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# 데이터베이스 초기화
def init_db():
    conn = sqlite3.connect('refrigerator.db')
    c = conn.cursor()
    
    # 기존 테이블 삭제
    c.execute('DROP TABLE IF EXISTS items')
    c.execute('DROP TABLE IF EXISTS categories')
    
    # 카테고리 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         name TEXT NOT NULL UNIQUE)
    ''')
    
    # 기본 카테고리 추가
    default_categories = ['육류', '유제품', '과일', '채소', '음료', '반찬', '기타']
    for category in default_categories:
        try:
            c.execute('INSERT INTO categories (name) VALUES (?)', (category,))
        except sqlite3.IntegrityError:
            pass  # 이미 존재하는 카테고리는 무시
    
    # 품목 테이블 생성
    c.execute('''
        CREATE TABLE IF NOT EXISTS items
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         name TEXT NOT NULL,
         category_id INTEGER,
         quantity INTEGER DEFAULT 1,
         purchase_date DATE NOT NULL,
         expiry_date DATE NOT NULL,
         notification_sent BOOLEAN DEFAULT 0,
         FOREIGN KEY (category_id) REFERENCES categories(id))
    ''')
    
    conn.commit()
    conn.close()

@app.route('/get_categories')
def get_categories():
    try:
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        c.execute('SELECT * FROM categories ORDER BY name')
        categories = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'categories': categories})
    except Exception as e:
        logging.error(f'카테고리 조회 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/add_item', methods=['POST'])
def add_item():
    try:
        item = request.form.get('item')
        category_id = request.form.get('category_id')
        quantity = request.form.get('quantity', 1, type=int)
        purchase_date = request.form.get('purchase_date')
        expiry_date = request.form.get('expiry_date')
        
        if not all([item, category_id, purchase_date, expiry_date]):
            return jsonify({'success': False, 'error': '모든 필드를 입력해주세요'})
        
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO items (name, category_id, quantity, purchase_date, expiry_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (item, category_id, quantity, purchase_date, expiry_date))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'{item} {quantity}개가 추가되었습니다'
        })
        
    except Exception as e:
        logging.error(f'품목 추가 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': f'오류가 발생했습니다: {str(e)}'}), 500

@app.route('/get_items')
def get_items():
    try:
        sort_by = request.args.get('sort', 'expiry_date')
        search = request.args.get('search', '')
        category_id = request.args.get('category_id', '')
        
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        
        query = '''
            SELECT i.*, c.name as category_name 
            FROM items i
            LEFT JOIN categories c ON i.category_id = c.id
            WHERE 1=1
        '''
        params = []
        
        if search:
            query += ' AND i.name LIKE ?'
            params.append(f'%{search}%')
        
        if category_id:
            query += ' AND i.category_id = ?'
            params.append(category_id)
            
        query += f' ORDER BY {sort_by}'
        
        c.execute(query, params)
        items = [{
            'id': row[0],
            'name': row[1],
            'category_id': row[2],
            'quantity': row[3],
            'purchase_date': row[4],
            'expiry_date': row[5],
            'category_name': row[7]
        } for row in c.fetchall()]
        
        # 유통기한 임박 알림 체크
        check_expiry_notifications(c)
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        logging.error(f'품목 조회 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

def check_expiry_notifications(cursor):
    today = datetime.now().date()
    warning_date = today + timedelta(days=3)
    
    # 아직 알림을 보내지 않은 임박 항목 조회
    cursor.execute('''
        SELECT id, name, expiry_date
        FROM items
        WHERE notification_sent = 0 
        AND date(expiry_date) <= date(?)
        AND date(expiry_date) >= date(?)
    ''', (warning_date, today))
    
    items = cursor.fetchall()
    for item in items:
        # 실제 서비스에서는 여기에 알림 발송 로직 구현
        # (이메일, 푸시 알림 등)
        logging.info(f'유통기한 임박 알림: {item[1]} (유통기한: {item[2]})')
        
        # 알림 발송 표시
        cursor.execute('''
            UPDATE items
            SET notification_sent = 1
            WHERE id = ?
        ''', (item[0],))

@app.route('/')
def index():
    try:
        return render_template('refrigerator.html')
    except Exception as e:
        logging.error(f'메인 페이지 오류: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/delete_item/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    try:
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        c.execute('DELETE FROM items WHERE id = ?', (item_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '삭제되었습니다'})
    except Exception as e:
        logging.error(f'품목 삭제 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/update_item/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    try:
        data = request.get_json()
        
        # 수량만 업데이트하는 경우
        if 'quantity' in data:
            conn = sqlite3.connect('refrigerator.db')
            c = conn.cursor()
            c.execute('''
                UPDATE items 
                SET quantity = ?
                WHERE id = ?
            ''', (data['quantity'], item_id))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '수량이 수정되었습니다'})
            
        # 전체 정보 업데이트하는 경우
        name = data.get('name')
        category_id = data.get('category_id')
        purchase_date = data.get('purchase_date')
        expiry_date = data.get('expiry_date')
        
        if not all([name, purchase_date, expiry_date]):
            return jsonify({'success': False, 'error': '모든 필드를 입력해주세요'})
        
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        c.execute('''
            UPDATE items 
            SET name = ?, purchase_date = ?, expiry_date = ?
            WHERE id = ?
        ''', (name, purchase_date, expiry_date, item_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': '수정되었습니다'})
    except Exception as e:
        logging.error(f'��목 수정 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

# 카테고리 추가 라우트
@app.route('/add_category', methods=['POST'])
def add_category():
    try:
        data = request.get_json()
        name = data.get('name')
        
        if not name:
            return jsonify({'success': False, 'error': '카테고리 이름을 입력해주세요'})
        
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        c.execute('INSERT INTO categories (name) VALUES (?)', (name,))
        conn.commit()
        
        # 새로 추가된 카테고리의 ID 가져오기
        category_id = c.lastrowid
        conn.close()
        
        return jsonify({
            'success': True,
            'category': {'id': category_id, 'name': name},
            'message': f'카테고리 "{name}"이(가) 추가되었습니다'
        })
        
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': '이미 존재하는 카테고리입니다'})
    except Exception as e:
        logging.error(f'카테고리 추가 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

# 카테고리 삭제 라우트
@app.route('/delete_category/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    try:
        conn = sqlite3.connect('refrigerator.db')
        c = conn.cursor()
        
        # 해당 카테고리를 사용하는 품목이 있는지 확인
        c.execute('SELECT COUNT(*) FROM items WHERE category_id = ?', (category_id,))
        count = c.fetchone()[0]
        
        if count > 0:
            return jsonify({
                'success': False, 
                'error': '이 카테고리에 속한 품목이 있어 삭제할 수 없습니다'
            })
        
        c.execute('DELETE FROM categories WHERE id = ?', (category_id,))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': '카테고리가 삭제되었습니다'
        })
        
    except Exception as e:
        logging.error(f'카테고리 삭제 중 오류 발생: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)

