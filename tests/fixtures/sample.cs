using System;
using System.Collections.Generic;

namespace MyApp.Services
{
    public class OrderService
    {
        private readonly IRepository _repo;

        public int Id { get; set; }
        public string Name { get; set; }

        public OrderService(IRepository repo)
        {
            _repo = repo;
        }

        [HttpGet]
        public async Task<Order> GetOrder(int orderId)
        {
            return await _repo.FindAsync(orderId);
        }

        [HttpPost]
        public async Task<bool> CancelOrder(int orderId)
        {
            return true;
        }

        private void Validate(Order order)
        {
        }
    }

    public class SimpleEntity
    {
        public int Id { get; set; }
        public string Description { get; set; }

        public SimpleEntity() {}
    }

    public interface IRepository
    {
        Task<Order> FindAsync(int id);
        void Save(Order order);
    }

    public class SqlRepository : IRepository, IDisposable
    {
        public Task<Order> FindAsync(int id) { return null; }
        public void Save(Order order) {}
        public void Dispose() {}
    }

    [ApiController]
    [Route("api/orders")]
    public class OrderController
    {
        [HttpGet("{id}")]
        public Order Get(int id) { return null; }

        [Authorize("Admin")]
        [HttpPost]
        public void Create(Order order) {}
    }

    // No modifier → internal by default
    class InternalHelper
    {
        void DoWork() {}
    }
}
