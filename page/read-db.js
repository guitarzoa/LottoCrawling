// page/read-db.js
// Requires: npm install mysql2
import mysql from 'mysql2/promise';

async function main() {
  const conn = await mysql.createConnection({
    host:   process.env.DB_HOST,
    port:   Number(process.env.DB_PORT),
    user:   process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME,
  });

  const [rows] = await conn.query('SELECT * FROM sample');
  console.log('🗒️ Sample data from DB:');
  rows.forEach(row => {
    console.log(`  • [${row.id}] ${row.name}`);
  });

  await conn.end();
}

main().catch(err => {
  console.error('❌ Error reading from DB:', err);
  process.exit(1);
});
