package main

import (
	"fmt"
	"net/http"
)

type OrderService struct {
	db *DB
}

func NewOrderService(db *DB) *OrderService {
	return &OrderService{db: db}
}

func (s *OrderService) GetOrder(id int) (*Order, error) {
	return nil, nil
}

func (s *OrderService) cancelOrder(id int) error {
	return nil
}

func HealthCheck(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintf(w, "ok")
}
