// page/read-db.js
const mysql = require('mysql2/promise');
const fs = require('fs');
const path = require('path');

async function main() {
  const {
    DB_HOST = '127.0.0.1',
    DB_PORT = '3800',
    DB_USER = 'test',
    DB_PASSWORD = 'pwtest',
    DB_NAME = 'test',
  } = process.env;

  let conn;
  try {
    conn = await mysql.createConnection({
      host: DB_HOST,
      port: +DB_PORT,
      user: DB_USER,
      password: DB_PASSWORD,
      database: DB_NAME,
    });

    // sample 테이블의 모든 행 조회
    const [rows] = await conn.query('SELECT * FROM sample');

    // JSON 파일로 저장
    const outPath = path.resolve(__dirname, '../results.json');
    fs.writeFileSync(outPath, JSON.stringify(rows, null, 2), 'utf-8');
    console.log(`✅ Query result saved to ${outPath}`);
  } catch (err) {
    console.error('❌ DB 조회 중 에러 발생:', err);
    process.exit(1);
  } finally {
    if (conn) await conn.end();
  }
}

main();
