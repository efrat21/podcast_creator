console.log('Squad dev server placeholder');
const http = require('http');
const port = process.env.PORT || 3000;
const server = http.createServer((req, res) => { res.end('Squad dev server placeholder'); });
server.listen(port, () => console.log('Listening on', port));
