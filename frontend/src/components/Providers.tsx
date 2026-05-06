'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { StreamingProvider, useStreaming } from '@/contexts/StreamingContext';
import { useLiveFeed } from '@/hooks/useLiveFeed';

/** Mounts the WebSocket feed inside the QueryClientProvider context. */
function LiveFeedMount() {
  const { isStreaming } = useStreaming();
  useLiveFeed(isStreaming);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        refetchOnWindowFocus: false,
      },
    },
  }));

  return (
    <QueryClientProvider client={queryClient}>
      <StreamingProvider>
        <LiveFeedMount />
        {children}
      </StreamingProvider>
    </QueryClientProvider>
  );
}
