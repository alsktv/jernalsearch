export async function onRequest(context) {
  const { request } = context;

  if (request.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'Method Not Allowed' }), { status: 405, headers: { 'Content-Type': 'application/json' } });
  }

  let body = {};
  try {
    body = await request.json();
  } catch (e) {
    // If JSON parsing fails, return a friendly error
    return new Response(JSON.stringify({ error: 'Invalid JSON body' }), { status: 400, headers: { 'Content-Type': 'application/json' } });
  }

  const title = body && body.title;

  // Simulate AI search delay (non-blocking)
  await new Promise((resolve) => setTimeout(resolve, 2000));

  if (!title) {
    return new Response(JSON.stringify({ error: '제목이 제공되지 않았습니다.' }), { status: 400, headers: { 'Content-Type': 'application/json' } });
  }

  const mock_refs = [
    { title: 'Mock Reference Paper 1', authors: 'John Doe', year: 2024 },
    { title: 'Mock Reference Paper 2', authors: 'Jane Smith', year: 2025 },
    { title: 'Mock Reference Paper 3', authors: 'Alex Brown', year: 2023 }
  ];

  return new Response(JSON.stringify({ references: mock_refs }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}
