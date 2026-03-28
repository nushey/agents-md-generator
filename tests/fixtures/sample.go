package main

import (
	"fmt"
	"net/http"
)

type IOrderRepo interface {
	FindAll() ([]*Order, error)
	FindByID(id int) (*Order, error)
	Save(order *Order) error
}

type OrderService struct {
	db *DB
}

type Config struct {
	Host string `json:"host" yaml:"host"`
	Port int    `json:"port" yaml:"port" validate:"required"`
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
