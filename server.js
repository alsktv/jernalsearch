const express = require('express');
const path = require('path');
const app = express();
const port = process.env.PORT || 5002;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

app.post('/api/find-references', (req, res) => {
  try {
    const title = req.body && req.body.title;
    // simulate AI search delay
    setTimeout(() => {
      if (!title) {
        return res.status(400).json({ error: '제목이 제공되지 않았습니다.' });
      }

      const mock_refs = [
        { title: 'Mock Reference Paper 1', authors: 'John Doe', year: 2024 },
        { title: 'Mock Reference Paper 2', authors: 'Jane Smith', year: 2025 },
        { title: 'Mock Reference Paper 3', authors: 'Alex Brown', year: 2023 }
      ];

      res.json({ references: mock_refs });
    }, 2000);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: '하위 논문을 찾지 못했습니다.' });
  }
});

// Fallback to index.html for SPA
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(port, () => {
  console.log(`Server listening on http://localhost:${port}`);
});
