import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Loader2, Send, Bot, User, Link as LinkIcon } from 'lucide-react';
import { ScrollArea } from '../components/ui/scroll-area';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const AskScopey = () => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [embeddingsReady, setEmbeddingsReady] = useState(false);
  const [generatingEmbeddings, setGeneratingEmbeddings] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    checkEmbeddings();
  }, []);

  const checkEmbeddings = async () => {
    try {
      const response = await axios.get(`${API}/stats`);
      setEmbeddingsReady(response.data.embeddings > 0);
    } catch (error) {
      console.error('Error checking embeddings:', error);
    }
  };

  const generateEmbeddings = async () => {
    setGeneratingEmbeddings(true);
    try {
      await axios.post(`${API}/embeddings/generate-all`);
      setEmbeddingsReady(true);
      alert('Embeddings generated successfully! You can now ask questions.');
    } catch (error) {
      console.error('Error generating embeddings:', error);
      alert('Error generating embeddings. Please try again.');
    } finally {
      setGeneratingEmbeddings(false);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await axios.post(`${API}/ask-scopey`, {
        question: input,
        history: messages
      });

      const assistantMessage = {
        role: 'assistant',
        content: response.data.answer,
        sources: response.data.sources
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error asking Scopey:', error);
      const errorMessage = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.'
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="space-y-8 h-[calc(100vh-200px)]">
      <div>
        <h1 className="text-4xl font-bold" data-testid="ask-scopey-title">Ask Scopey</h1>
        <p className="text-muted-foreground mt-2">
          RAG-powered assistant that answers questions about your projects
        </p>
      </div>

      {!embeddingsReady && (
        <Card className="border-blue-500 bg-blue-50 dark:bg-blue-950" data-testid="embeddings-setup-card">
          <CardHeader>
            <CardTitle className="text-blue-700 dark:text-blue-300">
              Setup Required
            </CardTitle>
            <CardDescription className="text-blue-600 dark:text-blue-400">
              Generate embeddings to enable semantic search
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              onClick={generateEmbeddings} 
              disabled={generatingEmbeddings}
              data-testid="generate-embeddings-btn"
            >
              {generatingEmbeddings ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Generating Embeddings...</>
              ) : (
                'Generate Embeddings'
              )}
            </Button>
            <p className="text-xs text-muted-foreground mt-2">
              This will index all your artifacts for semantic search. May take a minute.
            </p>
          </CardContent>
        </Card>
      )}

      <Card className="flex flex-col h-full" data-testid="chat-container">
        <CardHeader>
          <CardTitle className="flex items-center">
            <Bot className="mr-2 h-5 w-5" />
            Scopey Chat
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col space-y-4">
          <ScrollArea className="flex-1 pr-4">
            <div className="space-y-4">
              {messages.length === 0 && (
                <div className="text-center text-muted-foreground py-12" data-testid="empty-chat-message">
                  <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>Ask me anything about your projects!</p>
                  <p className="text-sm mt-2">I can search across Linear issues, GitHub PRs, Slack conversations, and docs.</p>
                </div>
              )}
              
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  data-testid={`chat-message-${index}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg p-4 ${
                      message.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted'
                    }`}
                  >
                    <div className="flex items-start space-x-2">
                      {message.role === 'assistant' && <Bot className="h-5 w-5 mt-1" />}
                      {message.role === 'user' && <User className="h-5 w-5 mt-1" />}
                      <div className="flex-1">
                        <p className="whitespace-pre-wrap">{message.content}</p>
                        {message.sources && message.sources.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-border">
                            <p className="text-xs font-semibold mb-2">Sources:</p>
                            <div className="space-y-1">
                              {message.sources.map((source, idx) => (
                                <Badge key={idx} variant="outline" className="text-xs mr-1">
                                  <LinkIcon className="h-3 w-3 mr-1" />
                                  {source.artifact_type} (similarity: {(source.similarity * 100).toFixed(0)}%)
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
              
              {loading && (
                <div className="flex justify-start" data-testid="loading-indicator">
                  <div className="bg-muted rounded-lg p-4">
                    <Loader2 className="h-5 w-5 animate-spin" />
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>

          <div className="flex space-x-2">
            <Input
              placeholder="Ask a question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={loading || !embeddingsReady}
              data-testid="chat-input"
            />
            <Button 
              onClick={sendMessage} 
              disabled={loading || !input.trim() || !embeddingsReady}
              data-testid="send-message-btn"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default AskScopey;