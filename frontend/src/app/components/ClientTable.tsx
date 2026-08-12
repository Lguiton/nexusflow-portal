// @ts-nocheck
'use client';

import { useState, useEffect } from 'react';

export default function ClientTable() {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/clients")
      .then(res => res.json())
      .then(data => {
        setClients(data);
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch clients", err);
        setLoading(false);
      });
  }, []);

  return (
    
      
        
          Client Directory
        
        
          Active and historical organization records.
        
      
      
        
            {loading ? (
              
            ) : (
              clients.map((client, idx) => (
                
              ))
            )}
          
          
            
              Client ID
              Status
              MRR
              Signup Date
            
          
          
                
                  Loading records...
                
              
                  {client.client_id}
                  
                    
                      {client.status}
                    
                  
                  ${client.mrr.toLocaleString()}
                  {client.signup_date}
                
        
      
    
  );
}