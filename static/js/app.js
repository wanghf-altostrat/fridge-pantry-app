document.addEventListener('DOMContentLoaded', () => {
  // State
  let inventory = [];
  let currentTab = 'all';
  let searchQuery = '';

  // DOM Elements
  const inventoryGrid = document.getElementById('inventory-grid');
  const searchInput = document.getElementById('inventory-search');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const statTotal = document.getElementById('stat-total');
  const statFridge = document.getElementById('stat-fridge');
  const statPantry = document.getElementById('stat-pantry');
  const statExpiring = document.getElementById('stat-expiring');

  // Form Elements
  const btnToggleAdd = document.getElementById('btn-toggle-add');
  const addItemContainer = document.getElementById('add-item-form-container');
  const addItemForm = document.getElementById('add-item-form');
  const btnCancelAdd = document.getElementById('btn-cancel-add');

  // Shopping List Elements
  const btnToggleShoppingList = document.getElementById('btn-toggle-shopping-list');
  const shoppingListContainer = document.getElementById('shopping-list-card-container');
  const shoppingListForm = document.getElementById('shopping-list-form');
  const shoppingListText = document.getElementById('shopping-list-text');
  const btnCancelShoppingList = document.getElementById('btn-cancel-shopping-list');

  // Global Actions
  const btnReset = document.getElementById('btn-reset');

  // Agent Chat Elements
  const chatMessages = document.getElementById('chat-messages');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const btnClearChat = document.getElementById('btn-clear-chat');
  const quickChips = document.querySelectorAll('.chip-btn');
  const hitlContainer = document.getElementById('hitl-container');
  const recipeCardsContainer = document.getElementById('recipe-cards-container');

  // Initialize
  fetchInventory();

  // Event Listeners - Tabs
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentTab = btn.dataset.tab;
      renderInventory();
    });
  });

  // Event Listener - Search
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value.toLowerCase().trim();
    renderInventory();
  });

  // Toggle Shopping List Form
  btnToggleShoppingList.addEventListener('click', () => {
    shoppingListContainer.classList.toggle('hidden');
    if (!shoppingListContainer.classList.contains('hidden')) {
      addItemContainer.classList.add('hidden'); // Close single item form if open
      shoppingListText.focus();
    }
  });

  btnCancelShoppingList.addEventListener('click', () => {
    shoppingListContainer.classList.add('hidden');
  });

  // Submit Shopping List Form
  shoppingListForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const rawList = shoppingListText.value.trim();
    if (!rawList) {
      showToast('Please enter a shopping list', 'error');
      return;
    }

    try {
      const res = await fetch('/api/inventory/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shopping_list: rawList }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Successfully imported ${data.added_count} items from shopping list!`);
        shoppingListForm.reset();
        shoppingListContainer.classList.add('hidden');
        await fetchInventory();

        // Also notify agent timeline
        appendChatMessage('user', `I submitted a shopping list:\n\n${rawList.split('\n').map(l => '- ' + l).join('\n')}`);
        appendChatMessage('agent', `🛒 **Shopping List Processed!** Added/Updated ${data.added_count} item(s) in your inventory.`);
      } else {
        showToast(data.error || 'Failed to parse shopping list', 'error');
      }
    } catch (err) {
      console.error(err);
      showToast('Error processing shopping list', 'error');
    }
  });

  // Toggle Add Item Form
  btnToggleAdd.addEventListener('click', () => {
    addItemContainer.classList.toggle('hidden');
    if (!addItemContainer.classList.contains('hidden')) {
      shoppingListContainer.classList.add('hidden'); // Close shopping list if open
      document.getElementById('item-name').focus();
      // Set default expiration date to +7 days
      const defaultExp = new Date();
      defaultExp.setDate(defaultExp.getDate() + 7);
      document.getElementById('item-expiration').value = defaultExp.toISOString().split('T')[0];
    }
  });

  btnCancelAdd.addEventListener('click', () => {
    addItemContainer.classList.add('hidden');
  });

  // Submit Add Item Form
  addItemForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('item-name').value;
    const quantity = document.getElementById('item-quantity').value;
    const category = document.getElementById('item-category').value;
    const expiration_date = document.getElementById('item-expiration').value;

    try {
      const res = await fetch('/api/inventory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, quantity, category, expiration_date }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Added ${name} to ${category}`);
        addItemForm.reset();
        addItemContainer.classList.add('hidden');
        await fetchInventory();
      } else {
        showToast(data.error || 'Failed to add item', 'error');
      }
    } catch (err) {
      console.error(err);
      showToast('Error adding item', 'error');
    }
  });

  // Global Actions
  const btnDiscardExpired = document.getElementById('btn-discard-expired');
  if (btnDiscardExpired) {
    btnDiscardExpired.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/inventory/discard-expired', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          if (data.discarded_count > 0) {
            showToast(`Discarded ${data.discarded_count} expired item(s) 🗑️`);
            appendChatMessage('user', 'Throw out all expired foods.');
            appendChatMessage('agent', `🗑️ **Expired Foods Discarded!** Safely thrown out ${data.discarded_count} expired item(s):\n${data.discarded_items.map(i => '- ' + i.name + ' (' + i.quantity + ')').join('\n')}`);
          } else {
            showToast('No expired items found! Your fridge & pantry are fresh ✨');
          }
          await fetchInventory();
        }
      } catch (err) {
        console.error(err);
        showToast('Error discarding expired items', 'error');
      }
    });
  }

  // Reset Inventory
  btnReset.addEventListener('click', async () => {
    if (confirm('Are you sure you want to reset inventory to default demo items?')) {
      try {
        const res = await fetch('/api/inventory/reset', { method: 'POST' });
        if (res.ok) {
          showToast('Inventory reset to sample items');
          await fetchInventory();
          hitlContainer.classList.add('hidden');
        }
      } catch (err) {
        console.error(err);
      }
    }
  });

  // Quick Action Chips
  quickChips.forEach(chip => {
    btnSendPrompt = chip.addEventListener('click', () => {
      const promptText = chip.dataset.prompt;
      sendAgentMessage(promptText);
    });
  });

  // Clear Chat
  btnClearChat.addEventListener('click', () => {
    chatMessages.innerHTML = `
      <div class="chat-message agent-msg">
        <div class="avatar">🤖</div>
        <div class="message-content">
          <p>Chat history cleared. How can I assist with your fridge & pantry inventory?</p>
        </div>
      </div>
    `;
    hitlContainer.classList.add('hidden');
  });

  // Chat Form Submit
  chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (text) {
      sendAgentMessage(text);
      chatInput.value = '';
    }
  });

  // Functions
  async function fetchInventory() {
    try {
      const res = await fetch('/api/inventory');
      const data = await res.json();
      inventory = data.inventory || [];
      updateStats(data.stats);
      renderInventory();
    } catch (err) {
      console.error('Failed to fetch inventory:', err);
    }
  }

  function updateStats(stats) {
    if (!stats) return;
    statTotal.textContent = stats.total || 0;
    statFridge.textContent = stats.fridge || 0;
    statPantry.textContent = stats.pantry || 0;
    statExpiring.textContent = stats.expiring_soon || 0;
  }

  function renderInventory() {
    inventoryGrid.innerHTML = '';

    const filtered = inventory.filter(item => {
      // Tab filter
      if (currentTab === 'fridge' && item.category !== 'fridge') return false;
      if (currentTab === 'pantry' && item.category !== 'pantry') return false;
      if (currentTab === 'expiring_soon' && item.status !== 'expiring_soon' && item.status !== 'expired') return false;

      // Search filter
      if (searchQuery) {
        return item.name.toLowerCase().includes(searchQuery) || 
               item.category.toLowerCase().includes(searchQuery);
      }
      return true;
    });

    if (filtered.length === 0) {
      inventoryGrid.innerHTML = `
        <div class="span-full" style="text-align: center; padding: 40px 20px; color: var(--text-dim);">
          <p>No food items found matching your filter.</p>
        </div>
      `;
      return;
    }

    filtered.forEach(item => {
      const card = document.createElement('div');
      card.className = `food-card status-${item.status}`;

      let daysLabel = `${item.days_left} days left`;
      if (item.days_left === 0) daysLabel = 'Expires today!';
      else if (item.days_left < 0) daysLabel = `Expired ${Math.abs(item.days_left)} days ago`;

      card.innerHTML = `
        <div class="food-header">
          <div class="food-name">${escapeHtml(item.name)}</div>
          <span class="category-tag">${item.category === 'fridge' ? '🧊 Fridge' : '🥫 Pantry'}</span>
        </div>
        <div class="food-meta">
          <span class="quantity-badge">Qty: ${escapeHtml(item.quantity)}</span>
        </div>
        <div class="expiration-indicator">
          <div class="exp-text">
            <span class="exp-pill ${item.status}">${daysLabel}</span>
            <span style="font-size: 0.72rem; color: var(--text-dim);">${item.expiration_date}</span>
          </div>
        </div>
        <div class="food-actions" style="display: flex; gap: 6px; justify-content: flex-end; align-items: center;">
          <button class="btn btn-ghost btn-sm btn-consume" title="Eat / Consume Item" data-name="${escapeHtml(item.name)}">
            Consume 🍽️
          </button>
          <button class="btn-delete" title="Remove Item" data-name="${escapeHtml(item.name)}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </div>
      `;

      card.querySelector('.btn-consume').addEventListener('click', async (e) => {
        const name = e.currentTarget.dataset.name;
        await consumeItem(name);
      });

      card.querySelector('.btn-delete').addEventListener('click', async (e) => {
        const name = e.currentTarget.dataset.name;
        await deleteInventoryItem(name);
      });

      inventoryGrid.appendChild(card);
    });
  }

  async function consumeItem(itemName) {
    try {
      const res = await fetch('/api/inventory/consume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: itemName }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Consumed '${itemName}' 🍽️`);
        await fetchInventory();
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function deleteInventoryItem(itemName) {
    try {
      const res = await fetch(`/api/inventory/${encodeURIComponent(itemName)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast(`Removed '${itemName}'`);
        await fetchInventory();
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function sendAgentMessage(userText) {
    appendChatMessage('user', userText);

    // Add typing indicator
    const typingId = appendTypingIndicator();

    try {
      const res = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userText }),
      });
      const data = await res.json();
      removeTypingIndicator(typingId);

      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(msg => {
          appendChatMessage('agent', msg);
        });
      }

      // Check HITL or recipe approval options
      if (data.hitl) {
        renderRecipeApprovalOptions(data.hitl.message);
      } else {
        hitlContainer.classList.add('hidden');
      }

      // Refresh inventory if state updated
      if (data.inventory) {
        inventory = data.inventory;
        renderInventory();
        fetchInventory(); // updates stats
      }
    } catch (err) {
      removeTypingIndicator(typingId);
      console.error(err);
      appendChatMessage('agent', 'Sorry, I encountered an error communicating with the agent.');
    }
  }

  async function cookRecipeChoice(choiceNumber, recipeName) {
    try {
      const res = await fetch('/api/agent/cook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe: choiceNumber }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Cooked ${recipeName}!`);
        hitlContainer.classList.add('hidden');
        appendChatMessage('agent', `👨‍🍳 **Cooked Recipe:** ${recipeName}\n\n✅ Automatically deducted consumed ingredients from your inventory.`);
        await fetchInventory();
      }
    } catch (err) {
      console.error(err);
    }
  }

  function renderRecipeApprovalOptions(message) {
    hitlContainer.classList.remove('hidden');
    recipeCardsContainer.innerHTML = '';

    const presetRecipes = [
      { id: '1', name: 'Chicken & Tomato Skillet', desc: 'Chicken Breast, Tomatoes' },
      { id: '2', name: 'Cheesy Omelette Delight', desc: 'Eggs, Milk' },
      { id: '3', name: 'Vegetable Pasta Stir-Fry', desc: 'Spinach, Tomatoes, Pasta' },
    ];

    presetRecipes.forEach(rec => {
      const card = document.createElement('div');
      card.className = 'recipe-option-card';
      card.innerHTML = `
        <div>
          <div class="recipe-opt-title">${rec.id}. ${rec.name}</div>
          <div class="recipe-opt-ingredients">Uses: ${rec.desc}</div>
        </div>
        <button class="btn btn-primary btn-sm btn-cook" data-id="${rec.id}" data-name="${rec.name}">
          Cook Recipe 🍳
        </button>
      `;

      card.querySelector('.btn-cook').addEventListener('click', (e) => {
        const id = e.currentTarget.dataset.id;
        const name = e.currentTarget.dataset.name;
        cookRecipeChoice(id, name);
      });

      recipeCardsContainer.appendChild(card);
    });
  }

  function appendChatMessage(sender, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${sender}-msg`;

    const avatar = sender === 'user' ? '👤' : '🤖';
    const parsedText = window.marked ? marked.parse(text) : escapeHtml(text);

    msgDiv.innerHTML = `
      <div class="avatar">${avatar}</div>
      <div class="message-content">${parsedText}</div>
    `;

    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function appendTypingIndicator() {
    const id = 'typing-' + Date.now();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'chat-message agent-msg';
    msgDiv.id = id;
    msgDiv.innerHTML = `
      <div class="avatar">🤖</div>
      <div class="message-content" style="color: var(--text-dim); italic;">
        Agent thinking...
      </div>
    `;
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
  }

  function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    if (type === 'error') toast.style.borderColor = 'var(--accent-rose)';
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
});
