import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export async function GET() {
  try {
    const res = await fetch('http://localhost:8000/health', { 
      // short timeout so we don't hang if it's down
      signal: AbortSignal.timeout(1000) 
    });
    if (res.ok) {
      return NextResponse.json({ running: true });
    }
  } catch (err) {
    // Expected to fail if server is unreachable
  }
  return NextResponse.json({ running: false });
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const action = body.action;

    if (action === 'stop') {
      try {
        // Find python processes listening on port 8000 or running main.py and kill them
        await execAsync('lsof -t -i :8000 | xargs kill -9');
      } catch (e) {
        // Ignored, maybe nothing to kill
      }
      try {
        await execAsync('pkill -f "python.*main.py"');
      } catch (e) {
        // Ignored
      }
      return NextResponse.json({ success: true, running: false });
    }

    if (action === 'start') {
      // Assuming command is run from frontend directory
      // So path to backend is ../backend
      const cmd = `cd ../backend && nohup ./venv/bin/python main.py > backend.log 2>&1 &`;
      exec(cmd);
      
      // Give it a short moment to spin up before returning
      await new Promise(r => setTimeout(r, 1500));
      return NextResponse.json({ success: true, running: true });
    }

    return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
  } catch (error) {
    console.error("Backend control err:", error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
